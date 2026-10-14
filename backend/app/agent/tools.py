"""Tool registry. Every tool declares access (read/write), data scope, sensitivity and whether it needs
human approval. The runtime enforces these declarations deterministically:

  * read tools run directly and only ever read the current user's rows;
  * write tools never execute inside an agent run: they create an ActionProposal that the user must
    approve, edit or reject in the UI (see app.api.routers.proposals);
  * the LLM never chooses tools or arguments from retrieved content (planning is done from the user's
    question only), so instructions hidden in emails/documents cannot trigger a tool.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal, cast

from sqlalchemy import or_, select

from app.core.timeutil import ensure_aware
from app.db import models as m
from app.ingestion.workspace import Workspace
from app.intelligence.briefs import commitment_item, meeting_brief
from app.intelligence.proactive import _source_label, project_health
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.query_parser import ParsedQuery

Access = Literal["read", "write"]


@dataclass
class Source:
    source_type: str
    source_id: str
    title: str
    text: str
    occurred_at: str | None = None
    integration_id: str | None = None
    location: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.source_type, self.source_id, self.text[:60])


@dataclass
class ToolResult:
    summary: str
    items: list[dict[str, Any]] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)


@dataclass
class Tool:
    name: str
    description: str
    access: Access
    scope: str
    sensitivity: Literal["low", "medium", "high"]
    requires_approval: bool
    fn: Callable[..., ToolResult] | None = None
    params: dict[str, str] = field(default_factory=dict)

    def manifest(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "access": self.access.upper(), "scope": self.scope.upper(),
                "sensitivity": self.sensitivity, "requires_approval": self.requires_approval, "params": self.params}


REGISTRY: dict[str, Tool] = {}


def tool(name: str, description: str, *, access: Access = "read", scope: str, sensitivity: str = "medium",
         requires_approval: bool = False, params: dict[str, str] | None = None) -> Callable[[Callable[..., ToolResult]], Callable[..., ToolResult]]:
    def deco(fn: Callable[..., ToolResult]) -> Callable[..., ToolResult]:
        if access == "write" and not requires_approval:
            raise ValueError(f"write tool {name} must require approval")
        REGISTRY[name] = Tool(name, description, access, scope, sensitivity, requires_approval, fn, params or {})  # type: ignore[arg-type]
        return fn

    return deco


# ------------------------------------------------------------------------------------- helpers


def _src_from_hit(ws: Workspace, h: Any) -> Source:
    text = h.snippet
    return Source(h.type, h.id, h.title, text, h.occurred_at.isoformat() if h.occurred_at else None, h.integration_id, h.location)


def _integration_for(ws: Workspace, source_type: str, source_id: str) -> str | None:
    from app.privacy.policy import integration_of

    return integration_of(ws.db, source_type, source_id)


def _commitment_sources(ws: Workspace, c: m.Commitment) -> list[Source]:
    out = [Source(c.source_type, c.source_id, _source_label(ws.db, c.source_type, c.source_id), c.evidence_span,
                  c.detected_at.isoformat(), _integration_for(ws, c.source_type, c.source_id))]
    if c.resolution_source_id and c.status in ("FULFILLED", "CANCELLED"):
        ev = ws.db.scalar(select(m.Evidence).where(m.Evidence.subject_id == c.id, m.Evidence.role.in_(["fulfillment", "change"])))
        out.append(Source(c.resolution_source_type or "email", c.resolution_source_id,
                          _source_label(ws.db, c.resolution_source_type or "email", c.resolution_source_id),
                          (ev.span if ev and ev.span else c.resolution_reason) or "", None,
                          _integration_for(ws, c.resolution_source_type or "email", c.resolution_source_id)))
    for ch in ws.db.scalars(select(m.CommitmentDueChange).where(m.CommitmentDueChange.commitment_id == c.id)):
        out.append(Source(ch.source_type, ch.source_id, _source_label(ws.db, ch.source_type, ch.source_id), ch.evidence_span,
                          ch.observed_at.isoformat(), _integration_for(ws, ch.source_type, ch.source_id)))
    return out


# ------------------------------------------------------------------------------------- read tools


@tool("search_memory", "Hybrid search (semantic + keyword + graph + structured) over all personal memory.",
      scope="all", params={"query": "text", "k": "int", "types": "optional list"})
def search_memory(ws: Workspace, pq: ParsedQuery, query: str, k: int = 8, types: list[str] | None = None,
                  use_time_filter: bool = True) -> ToolResult:
    r = HybridRetriever(ws.db, ws.user_id, now=ws.now(), tz=ws.tz, self_person_id=ws.self_person_id)
    res = r.search(query, k=k, types=set(types) if types else None, parsed=pq, use_time_filter=use_time_filter)
    srcs = []
    for h in res.hits:
        if h.type in ("commitment", "decision"):
            st, sid = h.extra.get("source_type"), h.extra.get("source_id")
            if st and sid:
                srcs.append(Source(st, sid, _source_label(ws.db, st, sid), h.snippet, h.occurred_at.isoformat() if h.occurred_at else None,
                                   _integration_for(ws, st, sid)))
        elif h.type != "task":
            srcs.append(_src_from_hit(ws, h))
    return ToolResult(f"{len(res.hits)} result(s) from hybrid search", [h.as_dict() for h in res.hits], srcs)


@tool("search_email", "Search emails only.", scope="email", params={"query": "text"})
def search_email(ws: Workspace, pq: ParsedQuery, query: str, k: int = 6) -> ToolResult:
    return search_memory(ws, pq, query, k=k, types=["email"])


@tool("search_documents", "Search documents only.", scope="files", params={"query": "text"})
def search_documents(ws: Workspace, pq: ParsedQuery, query: str, k: int = 6) -> ToolResult:
    return search_memory(ws, pq, query, k=k, types=["document"])


@tool("search_calendar", "Search meetings (titles, descriptions and notes).", scope="calendar", params={"query": "text"})
def search_calendar(ws: Workspace, pq: ParsedQuery, query: str, k: int = 6) -> ToolResult:
    return search_memory(ws, pq, query, k=k, types=["event"])


@tool("get_commitments", "Commitments/requests filtered by person, direction, status, project and time.", scope="commitments",
      params={"person_ids": "list", "direction": "owed_to_me|mine|any", "statuses": "list", "project_ids": "list"})
def get_commitments(ws: Workspace, pq: ParsedQuery, person_ids: list[str] | None = None, direction: str = "any",
                    statuses: list[str] | None = None, project_ids: list[str] | None = None, keywords: str = "",
                    actor_ids: list[str] | None = None) -> ToolResult:
    q = select(m.Commitment).where(m.Commitment.user_id == ws.user_id, m.Commitment.detected_at <= ws.now())
    if actor_ids:
        q = q.where(m.Commitment.actor_person_id.in_(actor_ids))
    if person_ids:
        q = q.where(or_(m.Commitment.actor_person_id.in_(person_ids), m.Commitment.recipient_person_id.in_(person_ids)))
    if direction == "owed_to_me":
        q = q.where(m.Commitment.actor_person_id != ws.self_person_id)
    elif direction == "mine":
        q = q.where(m.Commitment.actor_person_id == ws.self_person_id)
    if statuses:
        q = q.where(m.Commitment.status.in_(statuses))
    if project_ids:
        q = q.where(m.Commitment.project_id.in_(project_ids))
    if pq.time_start:
        q = q.where(m.Commitment.detected_at >= pq.time_start)
    if pq.time_end:
        q = q.where(m.Commitment.detected_at <= pq.time_end)
    rows = list(ws.db.scalars(q.order_by(m.Commitment.detected_at)))
    if keywords:
        kws = keywords.lower().split()
        scored = [(sum(1 for w in kws if w in f"{c.description} {c.evidence_span}".lower()), c) for c in rows]
        if any(s for s, _ in scored):
            rows = [c for s, c in scored if s > 0]
    items, srcs = [], []
    for c in rows[:15]:
        items.append(commitment_item(ws, c))
        srcs += _commitment_sources(ws, c)
    return ToolResult(f"{len(rows)} commitment(s)", items, srcs)


@tool("get_tasks", "Tasks filtered by status and project.", scope="tasks", params={"statuses": "list", "project_ids": "list"})
def get_tasks(ws: Workspace, pq: ParsedQuery, statuses: list[str] | None = None, project_ids: list[str] | None = None) -> ToolResult:
    q = select(m.Task).where(m.Task.user_id == ws.user_id)
    if statuses:
        q = q.where(m.Task.status.in_(statuses))
    if project_ids:
        q = q.where(m.Task.project_id.in_(project_ids))
    rows = list(ws.db.scalars(q.order_by(m.Task.due_at.asc().nullslast()).limit(20)))
    items, srcs = [], []
    for t in rows:
        blocker = ws.db.get(m.Person, t.blocked_by_person_id) if t.blocked_by_person_id else None
        item = {"ref": {"type": "task", "id": t.id}, "title": t.title, "status": t.status, "due_at": t.due_at.isoformat() if t.due_at else None,
                "blocked_by": blocker.display_name if blocker else None, "blocked_reason": t.blocked_reason, "source": {}}
        items.append(item)
        if t.blocked_reason and t.status == "blocked":
            src_email = ws.db.scalar(select(m.Relationship).where(m.Relationship.src_id == t.id, m.Relationship.rel_type == "BLOCKED_BY")
                                     .order_by(m.Relationship.observed_at.desc()).limit(1))
            if src_email and src_email.source_id:
                item["source"] = {"source_type": src_email.source_type or "email", "source_id": src_email.source_id}
                srcs.append(Source(src_email.source_type or "email", src_email.source_id,
                                   _source_label(ws.db, src_email.source_type or "email", src_email.source_id), t.blocked_reason,
                                   None, _integration_for(ws, src_email.source_type or "email", src_email.source_id)))
        elif t.source_id and t.source_type and t.evidence_span:
            srcs.append(Source(t.source_type, t.source_id, _source_label(ws.db, t.source_type, t.source_id), t.evidence_span,
                               None, _integration_for(ws, t.source_type, t.source_id)))
    return ToolResult(f"{len(rows)} task(s)", items, srcs)


@tool("get_decisions", "Decisions with supersession history, filtered by project/topic/status/time.", scope="decisions",
      params={"project_ids": "list", "status": "active|superseded|any", "keywords": "text"})
def get_decisions(ws: Workspace, pq: ParsedQuery, project_ids: list[str] | None = None, status: str = "any", keywords: str = "") -> ToolResult:
    q = select(m.Decision).where(m.Decision.user_id == ws.user_id, m.Decision.decided_at <= ws.now())
    if project_ids:
        q = q.where(m.Decision.project_id.in_(project_ids))
    if status != "any":
        q = q.where(m.Decision.status == status)
    if pq.time_start:
        q = q.where(m.Decision.decided_at >= pq.time_start)
    if pq.time_end:
        q = q.where(m.Decision.decided_at <= pq.time_end)
    rows = list(ws.db.scalars(q.order_by(m.Decision.decided_at)))
    if keywords:
        kws = [w for w in keywords.lower().split() if len(w) > 2]
        hit = [d for d in rows if any(w in f"{d.topic} {d.chosen} {' '.join(d.rejected)} {d.statement}".lower() for w in kws)]
        rows = hit or rows
    items, srcs = [], []
    for d in rows:
        sup = ws.db.get(m.Decision, d.superseded_by_id) if d.superseded_by_id else None
        items.append({"ref": {"type": "decision", "id": d.id}, "topic": d.topic, "chosen": d.chosen, "rejected": d.rejected,
                      "status": d.status, "decided_at": d.decided_at.isoformat(),
                      "source": {"source_type": d.source_type, "source_id": d.source_id},
                      "superseded_by": {"chosen": sup.chosen, "decided_at": sup.decided_at.isoformat(), "id": sup.id} if sup else None})
        srcs.append(Source(d.source_type, d.source_id, _source_label(ws.db, d.source_type, d.source_id), d.statement,
                           d.decided_at.isoformat(), _integration_for(ws, d.source_type, d.source_id)))
    return ToolResult(f"{len(rows)} decision(s)", items, srcs)


@tool("get_fact_history", "Temporal history of a fact (deadlines, employment, decisions): every value with validity dates.",
      scope="memory", params={"subject": "project|person", "attribute": "text"})
def get_fact_history(ws: Workspace, pq: ParsedQuery, subject_type: str, subject_id: str, attribute_prefix: str = "") -> ToolResult:
    q = select(m.Memory).where(m.Memory.user_id == ws.user_id, m.Memory.kind == "semantic", m.Memory.subject_type == subject_type,
                               m.Memory.subject_id == subject_id)
    if attribute_prefix:
        q = q.where(m.Memory.attribute.like(f"{attribute_prefix}%"))
    rows = list(ws.db.scalars(q.order_by(m.Memory.attribute, m.Memory.valid_from)))
    items, srcs = [], []
    for r in rows:
        if r.status == "archived" or (subject_type == "person" and r.attribute == "works_at"):
            continue  # employment is reported from the temporal graph below (one row per period)
        items.append({"attribute": r.attribute, "value": r.value, "content": r.content, "status": r.status,
                      "valid_from": r.valid_from.isoformat() if r.valid_from else None, "valid_to": r.valid_to.isoformat() if r.valid_to else None,
                      "source": {"source_type": r.source_type, "source_id": r.source_id}})
        if r.source_id and r.source_type:
            srcs.append(Source(r.source_type, r.source_id, _source_label(ws.db, r.source_type, r.source_id), r.evidence_span or r.content,
                               r.observed_at.isoformat() if r.observed_at else None, _integration_for(ws, r.source_type, r.source_id)))
    if subject_type == "person":
        edges = [e for e in ws.db.scalars(select(m.Relationship).where(
            m.Relationship.user_id == ws.user_id, m.Relationship.src_id == subject_id, m.Relationship.rel_type == "WORKS_AT",
            m.Relationship.status != "rejected"))]
        edges.sort(key=lambda e: ensure_aware(e.valid_from or e.observed_at))  # type: ignore[arg-type, return-value]
        periods: list[dict[str, Any]] = []
        for e in edges:  # collapse consecutive facts about the same organisation into one period
            if periods and periods[-1]["org_id"] == e.dst_id:
                p = periods[-1]
                p["valid_to"] = e.valid_to if e.valid_to and (p["valid_to"] is None or e.valid_to > p["valid_to"]) else p["valid_to"]
                if e.status == "active":
                    p["valid_to"], p["status"] = None, "active"
                p["edges"].append(e)
            else:
                periods.append({"org_id": e.dst_id, "valid_from": e.valid_from or e.observed_at, "valid_to": e.valid_to,
                                "status": e.status, "edges": [e]})
        for p in periods:
            org = ws.db.get(m.Organization, p["org_id"])
            first = p["edges"][0]
            sid = first.source_id or ws.db.scalar(select(m.Email.id).where(
                m.Email.sender_person_id == subject_id,
                m.Email.from_addr.like(f"%@{org.domain}" if org and org.domain else "%")).order_by(m.Email.sent_at).limit(1))
            st = first.source_type or "email"
            span = first.evidence_span or (f"Writing from an @{org.domain} address" if org and org.domain else "")
            items.append({"attribute": "works_at", "value": org.name if org else "?", "status": p["status"],
                          "valid_from": p["valid_from"].isoformat() if p["valid_from"] else None,
                          "valid_to": p["valid_to"].isoformat() if p["valid_to"] else None,
                          "basis": (first.properties or {}).get("basis") or "stated in a message",
                          "source": {"source_type": st, "source_id": sid}})
            if sid:
                srcs.append(Source(st, sid, _source_label(ws.db, st, sid), span, p["valid_from"].isoformat() if p["valid_from"] else None,
                                   _integration_for(ws, st, sid)))
            joined = next((e for e in p["edges"] if e.source_id and e.evidence_span and "join" in e.evidence_span.lower()), None)
            if joined:
                srcs.append(Source(joined.source_type or "email", joined.source_id, _source_label(ws.db, joined.source_type or "email", joined.source_id),
                                   joined.evidence_span or "", joined.valid_from.isoformat() if joined.valid_from else None,
                                   _integration_for(ws, joined.source_type or "email", joined.source_id)))
                items[-1]["source"] = {"source_type": joined.source_type or "email", "source_id": joined.source_id}
    return ToolResult(f"{len(items)} historical value(s)", items, srcs)


@tool("get_project", "Project overview with explained health signals, people, open items.", scope="projects", params={"project_id": "id"})
def get_project(ws: Workspace, pq: ParsedQuery, project_id: str) -> ToolResult:
    p = ws.db.get(m.Project, project_id)
    if not p or p.user_id != ws.user_id:
        return ToolResult("project not found")
    h = project_health(ws, p)
    members = [ws.db.get(m.Person, pm.person_id) for pm in ws.db.scalars(select(m.ProjectMember).where(m.ProjectMember.project_id == p.id))]
    open_c = list(ws.db.scalars(select(m.Commitment).where(m.Commitment.user_id == ws.user_id, m.Commitment.project_id == p.id, m.Commitment.status.in_(["OPEN", "OVERDUE"]))))
    items = [{"ref": {"type": "project", "id": p.id}, "name": p.name, "health": h.label, "signals": h.signals,
              "members": [x.display_name for x in members if x], "open_commitments": len(open_c),
              "overdue_commitments": sum(1 for c in open_c if c.status == "OVERDUE")}]
    srcs: list[Source] = []
    for c in open_c[:6]:
        srcs += _commitment_sources(ws, c)
    return ToolResult(f"{p.name}: {h.label}", items, srcs)


@tool("get_projects_overview", "Health of every active project, with signals.", scope="projects")
def get_projects_overview(ws: Workspace, pq: ParsedQuery) -> ToolResult:
    items, srcs = [], []
    for p in ws.db.scalars(select(m.Project).where(m.Project.user_id == ws.user_id, m.Project.archived.is_(False))):
        r = get_project(ws, pq, p.id)
        items += r.items
        srcs += r.sources[:3]
    items.sort(key=lambda i: {"At Risk": 0, "Attention Needed": 1}.get(i["health"], 2))
    return ToolResult(f"{len(items)} project(s)", items, srcs)


@tool("get_person", "Person profile: organisation history, aliases, open items, last interaction.", scope="people", params={"person_id": "id"})
def get_person(ws: Workspace, pq: ParsedQuery, person_id: str) -> ToolResult:
    p = ws.db.get(m.Person, person_id)
    if not p or p.user_id != ws.user_id:
        return ToolResult("person not found")
    hist = get_fact_history(ws, pq, "person", p.id)
    org = ws.db.get(m.Organization, p.organization_id) if p.organization_id else None
    open_c = list(ws.db.scalars(select(m.Commitment).where(m.Commitment.user_id == ws.user_id, m.Commitment.status.in_(["OPEN", "OVERDUE"]),
                                                           or_(m.Commitment.actor_person_id == p.id, m.Commitment.recipient_person_id == p.id))))
    items = [{"ref": {"type": "person", "id": p.id}, "name": p.display_name, "organization": org.name if org else None, "title": p.title,
              "last_interaction_at": p.last_interaction_at.isoformat() if p.last_interaction_at else None,
              "employment_history": [i for i in hist.items if i.get("attribute") == "works_at"],
              "open_items": [{"title": c.description, "status": c.status, "source_type": c.source_type, "source_id": c.source_id}
                             for c in open_c]}]
    srcs = hist.sources
    for c in open_c[:5]:
        srcs += _commitment_sources(ws, c)
    return ToolResult(f"profile of {p.display_name}", items, srcs)


@tool("get_timeline", "Chronological events for a project/person within a time range.", scope="memory",
      params={"project_ids": "list", "person_ids": "list"})
def get_timeline(ws: Workspace, pq: ParsedQuery, project_ids: list[str] | None = None, person_ids: list[str] | None = None,
                 kinds: list[str] | None = None) -> ToolResult:
    q = select(m.TimelineEvent).where(m.TimelineEvent.user_id == ws.user_id, m.TimelineEvent.occurred_at <= ws.now())
    if kinds:
        q = q.where(m.TimelineEvent.kind.in_(kinds))
    if project_ids:
        q = q.where(m.TimelineEvent.project_id.in_(project_ids))
    if pq.time_start:
        q = q.where(m.TimelineEvent.occurred_at >= pq.time_start)
    if pq.time_end:
        q = q.where(m.TimelineEvent.occurred_at <= pq.time_end)
    rows = [t for t in ws.db.scalars(q.order_by(m.TimelineEvent.occurred_at).limit(200))
            if not person_ids or set(person_ids) & set(t.person_ids or [])]
    rows = [t for t in rows if t.kind != "commitment"][:25] or rows[:25]
    items, srcs = [], []
    for t in rows:
        st, sid = t.ref_type, t.ref_id
        if st in ("decision",) and sid:
            d = ws.db.get(m.Decision, sid)
            if d:
                st, sid = d.source_type, d.source_id
        if st in ("commitment",) and sid:
            c = ws.db.get(m.Commitment, sid)
            if c:
                st, sid = c.source_type, c.source_id
        items.append({"occurred_at": t.occurred_at.isoformat(), "kind": t.kind, "title": t.title,
                      "source": {"source_type": st, "source_id": sid}})
        if st in ("email", "event", "document", "note") and sid:
            srcs.append(Source(st, sid, _source_label(ws.db, st, sid), t.detail or t.title, t.occurred_at.isoformat(), _integration_for(ws, st, sid)))
    return ToolResult(f"{len(items)} timeline event(s)", items, srcs)


@tool("find_related_entities", "Graph neighbours of an entity (people, projects, documents...).", scope="graph",
      params={"node_type": "text", "node_id": "id"})
def find_related_entities(ws: Workspace, pq: ParsedQuery, node_type: str, node_id: str) -> ToolResult:
    nb = ws.graph.neighborhood((node_type, node_id), limit=40)
    return ToolResult(f"{len(nb['nodes']) - 1} related node(s)", nb["nodes"], [])


@tool("retrieve_source", "Full text of one source item (email, document, meeting, note).", scope="all", sensitivity="high",
      params={"source_type": "text", "source_id": "id"})
def retrieve_source(ws: Workspace, pq: ParsedQuery, source_type: str, source_id: str) -> ToolResult:
    content_models: dict[str, m.ContentModel] = {"email": m.Email, "event": m.CalendarEvent, "document": m.Document, "note": m.Note}
    model = content_models.get(source_type)
    # Session.get on a union of model classes is typed as returning Base
    row = cast("m.ContentRow | None", ws.db.get(model, source_id)) if model else None
    if row is None or row.user_id != ws.user_id:
        return ToolResult("not found")
    text = getattr(row, "body", None) or getattr(row, "text", None) or getattr(row, "notes", None) or ""
    return ToolResult("source retrieved", [{"type": source_type, "id": source_id}],
                      [Source(source_type, source_id, _source_label(ws.db, source_type, source_id), text[:2500], None,
                              _integration_for(ws, source_type, source_id))])


@tool("generate_meeting_brief", "Assemble a sourced meeting brief (participants, emails, open items, decisions, docs).",
      scope="calendar", params={"event_id": "id"})
def generate_meeting_brief(ws: Workspace, pq: ParsedQuery, event_id: str) -> ToolResult:
    b = meeting_brief(ws, event_id)
    srcs: list[Source] = []
    srcs.append(Source("event", event_id, _source_label(ws.db, "event", event_id), b["event"].get("description") or b["event"]["title"],
                       b["event"]["start_at"], _integration_for(ws, "event", event_id)))
    for c in b["open_commitments"][:8]:
        for e in c["evidence"]:
            srcs.append(Source(e["source_type"], e["source_id"], e["label"], f"{c['title']} ({c['status']}; due {c['due_at'] or 'n/a'}): {e['span']}",
                               None, _integration_for(ws, e["source_type"], e["source_id"])))
    for d in b["decisions"][:4]:
        for e in d["evidence"]:
            srcs.append(Source(e["source_type"], e["source_id"], _source_label(ws.db, e["source_type"], e["source_id"]),
                               f"Decision ({d['status']}): {e['span']}", d["decided_at"], _integration_for(ws, e["source_type"], e["source_id"])))
    if b["previous_meeting"]:
        pm = b["previous_meeting"]
        srcs.append(Source("event", pm["ref"]["id"], f"Previous meeting “{pm['title']}”", pm["notes"] or "", pm["start_at"],
                           _integration_for(ws, "event", pm["ref"]["id"])))
    for e2 in b["recent_emails"][:4]:
        srcs.append(Source("email", e2["ref"]["id"], f"Email “{e2['subject']}”", e2["snippet"], e2["sent_at"], _integration_for(ws, "email", e2["ref"]["id"])))
    return ToolResult(f"brief for {b['event']['title']}", [b], srcs)


@tool("detect_followups", "Open follow-ups: overdue promises, unanswered requests, people awaiting replies.", scope="memory")
def detect_followups(ws: Workspace, pq: ParsedQuery, kinds: list[str] | None = None) -> ToolResult:
    q = select(m.Insight).where(m.Insight.user_id == ws.user_id, m.Insight.status == "open")
    if kinds:
        q = q.where(m.Insight.kind.in_(kinds))
    rows = list(ws.db.scalars(q.order_by(m.Insight.score.desc()).limit(12)))
    items, srcs = [], []
    for i in rows:
        e0 = i.evidence[0] if i.evidence else {}
        items.append({"kind": i.kind, "title": i.title, "explanation": i.explanation, "score": i.score,
                      "source": {"source_type": e0.get("source_type"), "source_id": e0.get("source_id")}})
        for e in i.evidence[:1]:
            srcs.append(Source(e["source_type"], e["source_id"], e.get("label") or e["source_type"], f"{i.title}. {i.explanation} Evidence: {e.get('span', '')}",
                               e.get("at"), _integration_for(ws, e["source_type"], e["source_id"])))
    return ToolResult(f"{len(rows)} follow-up(s)", items, srcs)


def find_event(ws: Workspace, pq: ParsedQuery) -> m.CalendarEvent | None:
    """Resolve 'my 11 AM meeting', "tomorrow's meeting", 'the Orion sync' to an event."""
    import re

    now = ws.now()
    q = select(m.CalendarEvent).where(m.CalendarEvent.user_id == ws.user_id)
    start, end = pq.time_start, pq.time_end
    if not start:
        start, end = now, now + timedelta(days=7)
    events = list(ws.db.scalars(q.where(m.CalendarEvent.start_at >= start, m.CalendarEvent.start_at <= end).order_by(m.CalendarEvent.start_at)))
    hm = re.search(r"\b(\d{1,2})(?::(\d\d))?\s*(am|pm)\b", pq.raw.lower())
    if hm:
        hour = int(hm.group(1)) % 12 + (12 if hm.group(3) == "pm" else 0)
        events = [e for e in events if ensure_aware(e.start_at).hour == hour] or events  # type: ignore[union-attr]
    if pq.project_ids:
        events = [e for e in events if e.project_id in pq.project_ids] or events
    words = [w for w in pq.keywords.split() if len(w) > 3]
    if words:
        events = [e for e in events if any(w in e.title.lower() for w in words)] or events
    upcoming = [e for e in events if ensure_aware(e.end_at) >= now]  # type: ignore[operator]
    return next(iter(upcoming or events), None)


# ------------------------------------------------------------------------------------- write tools (approval-gated)


@tool("draft_email", "Prepare an email draft for the user to review. Never sends.", access="write", scope="email",
      sensitivity="high", requires_approval=True, params={"to": "email", "subject": "text", "body": "text"})
def draft_email(ws: Workspace, pq: ParsedQuery, **kw: Any) -> ToolResult:  # executed only via approved proposal
    return ToolResult("draft prepared")


@tool("send_email", "Send an email on the user's behalf.", access="write", scope="email", sensitivity="high",
      requires_approval=True, params={"to": "email", "subject": "text", "body": "text"})
def send_email(ws: Workspace, pq: ParsedQuery, **kw: Any) -> ToolResult:
    return ToolResult("not executed")


@tool("create_task", "Create a task.", access="write", scope="tasks", sensitivity="low", requires_approval=True,
      params={"title": "text", "due_at": "date", "project_id": "id"})
def create_task(ws: Workspace, pq: ParsedQuery, **kw: Any) -> ToolResult:
    return ToolResult("not executed")


@tool("delete_document", "Delete a document and everything derived from it.", access="write", scope="files", sensitivity="high",
      requires_approval=True, params={"document_id": "id"})
def delete_document(ws: Workspace, pq: ParsedQuery, **kw: Any) -> ToolResult:
    return ToolResult("not executed")


@tool("modify_calendar", "Create or change a calendar event.", access="write", scope="calendar", sensitivity="high",
      requires_approval=True, params={"event_id": "id"})
def modify_calendar(ws: Workspace, pq: ParsedQuery, **kw: Any) -> ToolResult:
    return ToolResult("not executed")


_ = datetime
