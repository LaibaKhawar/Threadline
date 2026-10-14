"""People (profiles, aliases, merge/split, merge candidates) and the knowledge graph API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.api.deps import workspace
from app.api.serialize import commitment_dict, decision_dict, email_dict, event_dict, iso, project_brief, task_dict
from app.db import models as m
from app.ingestion.workspace import Workspace
from app.memory.graph import NODE_MODELS, node_label

router = APIRouter(prefix="/api", tags=["people", "graph"])


@router.get("/people")
def people(q: str | None = None, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    db = ws.db
    query = select(m.Person).where(m.Person.user_id == ws.user_id, m.Person.merged_into_id.is_(None))
    if q:
        query = query.where(or_(m.Person.display_name.ilike(f"%{q}%"), m.Person.primary_email.ilike(f"%{q}%")))
    rows = list(db.scalars(query.order_by(m.Person.last_interaction_at.desc().nullslast(), m.Person.display_name)))
    out = []
    for p in rows:
        org = db.get(m.Organization, p.organization_id) if p.organization_id else None
        open_items = db.scalar(select(func.count()).select_from(m.Commitment).where(
            m.Commitment.status.in_(["OPEN", "OVERDUE"]), or_(m.Commitment.actor_person_id == p.id, m.Commitment.recipient_person_id == p.id))) or 0
        n_emails = db.scalar(select(func.count()).select_from(m.Email).where(m.Email.sender_person_id == p.id)) or 0
        out.append({"id": p.id, "name": p.display_name, "email": p.primary_email, "title": p.title, "organization": org.name if org else None,
                    "is_self": p.is_self, "last_interaction_at": iso(p.last_interaction_at), "open_items": open_items, "emails_sent": n_emails})
    cands = [{"id": c.id, "a": _pb(db, c.person_a_id), "b": _pb(db, c.person_b_id), "score": c.score, "reasons": c.reasons}
             for c in db.scalars(select(m.MergeCandidate).where(m.MergeCandidate.user_id == ws.user_id, m.MergeCandidate.status == "pending"))]
    return {"now": ws.now().isoformat(), "items": out, "merge_candidates": cands}


def _pb(db: Any, pid: str) -> dict[str, Any] | None:
    p = db.get(m.Person, pid)
    if not p:
        return None
    aliases = [a.alias for a in db.scalars(select(m.PersonAlias).where(m.PersonAlias.person_id == pid))]
    return {"id": p.id, "name": p.display_name, "email": p.primary_email, "aliases": aliases}


@router.get("/people/{pid}")
def person(pid: str, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    db = ws.db
    p = db.get(m.Person, pid)
    if not p or p.user_id != ws.user_id:
        raise HTTPException(404, "not found")
    if p.merged_into_id:
        return {"redirect": p.merged_into_id}
    org = db.get(m.Organization, p.organization_id) if p.organization_id else None
    aliases = [{"id": a.id, "alias": a.alias, "kind": a.kind} for a in db.scalars(select(m.PersonAlias).where(m.PersonAlias.person_id == pid))]
    employment = []
    for e in db.scalars(select(m.Relationship).where(m.Relationship.user_id == ws.user_id, m.Relationship.src_id == pid,
                                                     m.Relationship.rel_type == "WORKS_AT", m.Relationship.status != "rejected").order_by(m.Relationship.valid_from)):
        o = db.get(m.Organization, e.dst_id)
        employment.append({"organization": o.name if o else "?", "valid_from": iso(e.valid_from), "valid_to": iso(e.valid_to), "status": e.status,
                           "confidence": e.confidence, "basis": (e.properties or {}).get("basis"), "title": (e.properties or {}).get("title"),
                           "evidence": {"source_type": e.source_type, "source_id": e.source_id, "span": e.evidence_span} if e.source_id else None})
    project_ids = {pm.project_id for pm in db.scalars(select(m.ProjectMember).where(m.ProjectMember.person_id == pid))}
    emails = list(db.scalars(select(m.Email).where(m.Email.user_id == ws.user_id, m.Email.sent_at <= ws.now(), or_(
        m.Email.sender_person_id == pid,
        m.Email.id.in_(select(m.Relationship.src_id).where(m.Relationship.rel_type == "SENT_TO", m.Relationship.dst_id == pid))))
        .order_by(m.Email.sent_at.desc()).limit(25)))
    for em in emails:
        if em.project_id:
            project_ids.add(em.project_id)
    meetings = list(db.scalars(select(m.CalendarEvent).join(m.EventParticipant, m.EventParticipant.event_id == m.CalendarEvent.id)
                               .where(m.EventParticipant.person_id == pid).order_by(m.CalendarEvent.start_at.desc()).limit(25)))
    commitments = list(db.scalars(select(m.Commitment).where(or_(m.Commitment.actor_person_id == pid, m.Commitment.recipient_person_id == pid),
                                                             m.Commitment.detected_at <= ws.now()).order_by(m.Commitment.detected_at.desc())))
    decisions = [d for d in db.scalars(select(m.Decision).where(m.Decision.user_id == ws.user_id).order_by(m.Decision.decided_at.desc())) if pid in (d.participants or [])]
    tasks = list(db.scalars(select(m.Task).where(m.Task.user_id == ws.user_id, or_(m.Task.owner_person_id == pid, m.Task.blocked_by_person_id == pid))))
    timeline = [t for t in db.scalars(select(m.TimelineEvent).where(m.TimelineEvent.user_id == ws.user_id, m.TimelineEvent.occurred_at <= ws.now())
                                      .order_by(m.TimelineEvent.occurred_at.desc()).limit(400)) if pid in (t.person_ids or [])][:40]
    waiting = [c for c in commitments if c.actor_person_id == pid and c.status in ("OPEN", "OVERDUE")]
    owe = [c for c in commitments if c.actor_person_id == ws.self_person_id and c.recipient_person_id == pid and c.status in ("OPEN", "OVERDUE")]
    return {"id": p.id, "name": p.display_name, "email": p.primary_email, "title": p.title, "organization": org.name if org else None,
            "is_self": p.is_self, "notes": p.notes, "created_by": p.created_by, "last_interaction_at": iso(p.last_interaction_at),
            "aliases": aliases, "employment": employment,
            "projects": [x for x in (project_brief(db, i) for i in project_ids) if x],
            "waiting_on_them": [commitment_dict(db, c) for c in waiting], "you_owe_them": [commitment_dict(db, c) for c in owe],
            "emails": [email_dict(db, e) for e in emails], "meetings": [event_dict(db, e) for e in meetings],
            "commitments": [commitment_dict(db, c) for c in commitments], "decisions": [decision_dict(db, d) for d in decisions],
            "tasks": [task_dict(db, t) for t in tasks],
            "timeline": [{"occurred_at": iso(t.occurred_at), "kind": t.kind, "title": t.title, "ref": {"type": t.ref_type, "id": t.ref_id}} for t in timeline]}


class PersonPatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    title: str | None = Field(default=None, max_length=200)
    notes: str | None = None


@router.patch("/people/{pid}")
def patch_person(pid: str, body: PersonPatch, ws: Workspace = Depends(workspace)) -> dict[str, bool]:
    p = ws.db.get(m.Person, pid)
    if not p or p.user_id != ws.user_id:
        raise HTTPException(404, "not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    ws.db.commit()
    return {"ok": True}


class MergeIn(BaseModel):
    keep_id: str
    merge_id: str


@router.post("/people/merge")
def merge(body: MergeIn, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    try:
        keep = ws.resolver.merge(body.keep_id, body.merge_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    ws.db.add(m.Correction(user_id=ws.user_id, kind="person_merge", target_type="person", target_id=keep.id,
                           before={"merged": body.merge_id}, after={"into": keep.id}))
    ws.db.add(m.AuditLog(user_id=ws.user_id, actor="user", action="person_merge", target_type="person", target_id=keep.id,
                         details={"merged": body.merge_id}))
    ws.db.commit()
    return {"ok": True, "id": keep.id}


class SplitIn(BaseModel):
    alias_ids: list[str]
    new_name: str | None = None


@router.post("/people/{pid}/split")
def split(pid: str, body: SplitIn, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    try:
        new = ws.resolver.split(pid, body.alias_ids, body.new_name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    ws.db.add(m.Correction(user_id=ws.user_id, kind="person_split", target_type="person", target_id=pid,
                           before={"aliases": body.alias_ids}, after={"new_person": new.id}))
    ws.db.commit()
    return {"ok": True, "id": new.id}


class CandidateIn(BaseModel):
    action: str = Field(pattern="^(merge|reject)$")


@router.post("/people/merge-candidates/{cid}")
def decide_candidate(cid: str, body: CandidateIn, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    c = ws.db.get(m.MergeCandidate, cid)
    if not c or c.user_id != ws.user_id:
        raise HTTPException(404, "not found")
    if body.action == "reject":
        c.status = "rejected"
        ws.db.add(m.Correction(user_id=ws.user_id, kind="merge_rejected", target_type="person", target_id=c.person_a_id,
                               before={}, after={"not_same_as": c.person_b_id}))
        ws.db.commit()
        return {"ok": True}
    a, b = ws.db.get(m.Person, c.person_a_id), ws.db.get(m.Person, c.person_b_id)
    keep, gone = (a, b) if (a and (a.created_by == "contacts" or a.created_at <= b.created_at)) else (b, a)  # type: ignore[union-attr, operator]
    assert keep and gone
    ws.resolver.merge(keep.id, gone.id)
    c.status = "merged"
    ws.db.add(m.Correction(user_id=ws.user_id, kind="person_merge", target_type="person", target_id=keep.id, before={"merged": gone.id}, after={}))
    ws.db.commit()
    return {"ok": True, "id": keep.id}


# ------------------------------------------------------------------------------------- graph


@router.get("/graph/node/{node_type}/{node_id}")
def graph_node(node_type: str, node_id: str, rel_types: str | None = None, as_of: datetime | None = None,
               date_from: datetime | None = None, date_to: datetime | None = None, limit: int = Query(60, le=300),
               ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    if node_type not in NODE_MODELS:
        raise HTTPException(400, "unknown node type")
    row = ws.db.get(NODE_MODELS[node_type], node_id)
    if row is None or row.user_id != ws.user_id:
        raise HTTPException(404, "not found")
    return ws.graph.neighborhood((node_type, node_id), rel_types=rel_types.split(",") if rel_types else None, as_of=as_of,
                                 limit=limit, date_from=date_from, date_to=date_to)


@router.get("/graph/search")
def graph_search(q: str = Query(min_length=1, max_length=200), ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    out = []
    like = f"%{q}%"
    # heterogeneous model list: every entry is a UserOwned model with an ``id``
    searchable: tuple[tuple[str, Any, Any], ...] = (
                          ("person", m.Person, m.Person.display_name), ("project", m.Project, m.Project.name),
                          ("organization", m.Organization, m.Organization.name), ("document", m.Document, m.Document.title),
                          ("event", m.CalendarEvent, m.CalendarEvent.title), ("topic", m.Topic, m.Topic.name),
                          ("decision", m.Decision, m.Decision.chosen), ("commitment", m.Commitment, m.Commitment.description),
                          ("email", m.Email, m.Email.subject), ("note", m.Note, m.Note.title), ("task", m.Task, m.Task.title),
                          ("thread", m.EmailThread, m.EmailThread.subject),
    )
    for t, model, col in searchable:
        extra = [m.Person.merged_into_id.is_(None)] if model is m.Person else []
        for r in ws.db.scalars(select(model).where(model.user_id == ws.user_id, col.ilike(like), *extra).limit(8)):
            out.append({"id": f"{t}:{r.id}", "type": t, "ref_id": r.id, "label": node_label(r, t)})
    return {"items": out[:40]}


@router.get("/graph/overview")
def graph_overview(ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    """Starting view: projects, self and the most connected people (not the whole graph)."""
    db = ws.db
    seeds: list[tuple[str, str]] = [("project", p.id) for p in db.scalars(select(m.Project).where(m.Project.user_id == ws.user_id, m.Project.archived.is_(False)))]
    top = db.execute(select(m.Relationship.src_id, func.count()).where(m.Relationship.user_id == ws.user_id, m.Relationship.src_type == "person",
                                                                       m.Relationship.status == "active")
                     .group_by(m.Relationship.src_id).order_by(func.count().desc()).limit(8)).all()
    seeds += [("person", pid) for pid, _ in top]
    labels = ws.graph.labels(seeds)
    nodes = [{"id": f"{t}:{i}", "type": t, "ref_id": i, **labels.get((t, i), {"label": "?"})} for t, i in seeds if (t, i) in labels]
    ids = {i for _, i in seeds}
    edges = [ws.graph.edge_dict(e) for e in db.scalars(select(m.Relationship).where(
        m.Relationship.user_id == ws.user_id, m.Relationship.status == "active", m.Relationship.src_id.in_(ids), m.Relationship.dst_id.in_(ids)))]
    counts = dict(db.execute(select(m.Relationship.rel_type, func.count()).where(m.Relationship.user_id == ws.user_id,
                                                                                  m.Relationship.status == "active").group_by(m.Relationship.rel_type)).all())
    return {"nodes": nodes, "edges": edges, "edge_type_counts": counts}


@router.post("/graph/edges/{eid}/reject")
def reject_edge(eid: str, ws: Workspace = Depends(workspace)) -> dict[str, bool]:
    e = ws.graph.reject_edge(eid)
    if e is None:
        raise HTTPException(404, "not found")
    ws.db.add(m.Correction(user_id=ws.user_id, kind="edge_rejected", target_type="relationship", target_id=eid,
                           before={"rel": e.rel_type, "src": e.src_id, "dst": e.dst_id}, after={"status": "rejected"}))
    ws.db.commit()
    return {"ok": True}
