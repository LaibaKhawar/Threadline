"""Daily briefing and meeting briefs. Deterministic assembly from the memory layer; every item carries
a reference (type + id) and, where it came from text, the exact evidence span."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import false, func, or_, select

from app.core.timeutil import ensure_aware
from app.db import models as m
from app.ingestion.workspace import Workspace
from app.intelligence.proactive import _source_label, project_health
from app.retrieval.hybrid import HybridRetriever

DEFAULT_SECTIONS = ["today", "meetings", "deadlines", "tasks", "overdue", "awaiting", "followups", "projects", "changes"]


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _person(ws: Workspace, pid: str | None) -> str | None:
    if not pid:
        return None
    if pid == ws.self_person_id:
        return "You"
    p = ws.db.get(m.Person, pid)
    return p.display_name if p else None


def commitment_item(ws: Workspace, c: m.Commitment) -> dict[str, Any]:
    return {
        "ref": {"type": "commitment", "id": c.id}, "title": c.description, "status": c.status, "kind": c.kind,
        "actor": _person(ws, c.actor_person_id) or c.actor_text, "recipient": _person(ws, c.recipient_person_id),
        "due_at": _iso(c.due_at), "confidence": c.confidence, "reason": c.resolution_reason,
        "evidence": [{"source_type": c.source_type, "source_id": c.source_id, "span": c.evidence_span,
                      "label": _source_label(ws.db, c.source_type, c.source_id)}],
    }


def daily_briefing(ws: Workspace) -> dict[str, Any]:
    db, now = ws.db, ws.now()
    cfg = ws.settings.briefing_config or {}
    sections = cfg.get("sections") or DEFAULT_SECTIONS
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    out: dict[str, Any] = {"generated_at": now.isoformat(), "clock_pinned": ws.settings.clock_override is not None, "sections": {}}
    S = out["sections"]

    meetings = list(db.scalars(select(m.CalendarEvent).where(m.CalendarEvent.user_id == ws.user_id,
                                                             m.CalendarEvent.start_at >= day_start,
                                                             m.CalendarEvent.start_at < day_end + timedelta(days=1))
                               .order_by(m.CalendarEvent.start_at)))
    if "meetings" in sections:
        S["meetings"] = [{"ref": {"type": "event", "id": e.id}, "title": e.title, "start_at": _iso(e.start_at), "end_at": _iso(e.end_at),
                          "attendees": [a.get("name") or a.get("email") for a in (e.attendees or []) if (a.get("email") or "").lower() not in ws.self_emails],
                          "is_today": ensure_aware(e.start_at) < day_end} for e in meetings]  # type: ignore[operator]
    open_c = list(db.scalars(select(m.Commitment).where(m.Commitment.user_id == ws.user_id, m.Commitment.status.in_(["OPEN", "OVERDUE"]))))
    if "deadlines" in sections:
        soon = [c for c in open_c if c.due_at and now <= ensure_aware(c.due_at) <= now + timedelta(days=3)]  # type: ignore[operator]
        tasks_soon = list(db.scalars(select(m.Task).where(m.Task.user_id == ws.user_id, m.Task.status.in_(["active", "blocked"]),
                                                          m.Task.due_at >= now, m.Task.due_at <= now + timedelta(days=3))))
        S["deadlines"] = sorted([commitment_item(ws, c) for c in soon] +
                                [{"ref": {"type": "task", "id": t.id}, "title": t.title, "due_at": _iso(t.due_at), "status": t.status,
                                  "evidence": []} for t in tasks_soon], key=lambda x: x["due_at"] or "")
    if "tasks" in sections:
        tasks = list(db.scalars(select(m.Task).where(m.Task.user_id == ws.user_id, m.Task.status.in_(["active", "blocked"]))
                                .order_by(m.Task.due_at.asc().nullslast()).limit(8)))
        S["tasks"] = [{"ref": {"type": "task", "id": t.id}, "title": t.title, "due_at": _iso(t.due_at), "status": t.status,
                       "priority": t.priority, "overdue": bool(t.due_at and ensure_aware(t.due_at) < now)} for t in tasks]  # type: ignore[operator]
        S["suggested_tasks"] = db.scalar(select(func.count()).select_from(m.Task).where(m.Task.user_id == ws.user_id, m.Task.status == "suggested")) or 0
    if "overdue" in sections:
        S["overdue"] = [commitment_item(ws, c) for c in open_c if c.status == "OVERDUE"]
    insights = list(db.scalars(select(m.Insight).where(m.Insight.user_id == ws.user_id, m.Insight.status == "open")
                               .order_by(m.Insight.score.desc())))
    if "awaiting" in sections:
        S["awaiting"] = [_insight(i) for i in insights if i.kind == "awaiting_my_reply"][:6]
    if "followups" in sections:
        S["followups"] = [_insight(i) for i in insights if i.kind in ("unanswered_request", "possible_fulfillment", "blocked")][:6]
    if "projects" in sections:
        projs: list[dict[str, Any]] = []
        for p in db.scalars(select(m.Project).where(m.Project.user_id == ws.user_id, m.Project.archived.is_(False))):
            h = project_health(ws, p)
            projs.append({"ref": {"type": "project", "id": p.id}, "title": p.name, "status": h.status, "label": h.label,
                          "signals": h.signals, "score": h.score})
        S["projects"] = sorted(projs, key=lambda x: -x["score"])
    if "changes" in sections:
        changes = list(db.scalars(select(m.TimelineEvent).where(
            m.TimelineEvent.user_id == ws.user_id, m.TimelineEvent.occurred_at <= now, m.TimelineEvent.occurred_at >= now - timedelta(days=7),
            m.TimelineEvent.kind.in_(["decision", "deadline_change", "commitment_fulfilled", "commitment_cancelled", "employment"]))
            .order_by(m.TimelineEvent.occurred_at.desc()).limit(8)))
        S["changes"] = [{"ref": {"type": t.ref_type, "id": t.ref_id}, "title": t.title, "occurred_at": _iso(t.occurred_at),
                         "kind": t.kind, "detail": t.detail} for t in changes]
    today_meetings = [x for x in S.get("meetings", []) if x["is_today"]]
    S["today"] = {
        "meetings_today": len(today_meetings),
        "deadlines_soon": len(S.get("deadlines", [])),
        "overdue_commitments": len(S.get("overdue", [])),
        "people_awaiting": len(S.get("awaiting", [])),
        "projects_attention": [p["title"] for p in S.get("projects", []) if p["status"] in ("attention", "at_risk")],
    }
    return out


def _insight(i: m.Insight) -> dict[str, Any]:
    return {"ref": {"type": i.ref_type, "id": i.ref_id}, "insight_id": i.id, "kind": i.kind, "title": i.title,
            "explanation": i.explanation, "evidence": i.evidence, "score": i.score, "confidence": i.confidence,
            "suggested_action": i.suggested_action}


def meeting_brief(ws: Workspace, event_id: str) -> dict[str, Any]:
    db, now = ws.db, ws.now()
    ev = db.get(m.CalendarEvent, event_id)
    if ev is None or ev.user_id != ws.user_id:
        raise LookupError("event not found")
    pids = [p for p in db.scalars(select(m.EventParticipant.person_id).where(m.EventParticipant.event_id == ev.id)) if p != ws.self_person_id]
    participants = []
    for pid in pids:
        p = db.get(m.Person, pid)
        if not p:
            continue
        org = db.get(m.Organization, p.organization_id) if p.organization_id else None
        participants.append({"ref": {"type": "person", "id": p.id}, "name": p.display_name, "title": p.title,
                             "organization": org.name if org else None,
                             "last_interaction_at": _iso(p.last_interaction_at)})
    window = now - timedelta(days=30)
    emails = list(db.scalars(select(m.Email).where(
        m.Email.user_id == ws.user_id, m.Email.sent_at >= window, m.Email.sent_at <= now,
        or_(m.Email.sender_person_id.in_(pids), m.Email.project_id == ev.project_id if ev.project_id else false()))
        .order_by(m.Email.sent_at.desc()).limit(8)))
    commitments = list(db.scalars(select(m.Commitment).where(
        m.Commitment.user_id == ws.user_id, m.Commitment.status.in_(["OPEN", "OVERDUE", "UNCERTAIN"]),
        or_(m.Commitment.actor_person_id.in_(pids), m.Commitment.recipient_person_id.in_(pids),
            m.Commitment.project_id == ev.project_id if ev.project_id else false()))
        .order_by(m.Commitment.due_at.asc().nullslast())))
    decisions = []
    if ev.project_id:
        decisions = list(db.scalars(select(m.Decision).where(m.Decision.user_id == ws.user_id, m.Decision.project_id == ev.project_id)
                                    .order_by(m.Decision.decided_at.desc()).limit(6)))
    previous = db.scalar(select(m.CalendarEvent).where(
        m.CalendarEvent.user_id == ws.user_id, m.CalendarEvent.title == ev.title, m.CalendarEvent.start_at < ev.start_at,
        m.CalendarEvent.notes.is_not(None)).order_by(m.CalendarEvent.start_at.desc()))
    docs: list[dict[str, Any]] = []
    if ev.project_id:
        for d in db.scalars(select(m.Document).where(m.Document.user_id == ws.user_id, m.Document.project_id == ev.project_id)
                            .order_by(m.Document.authored_at.desc().nullslast()).limit(5)):
            docs.append({"ref": {"type": "document", "id": d.id}, "title": d.title, "authored_at": _iso(d.authored_at)})
    if len(docs) < 3:
        r = HybridRetriever(db, ws.user_id, now=now, tz=ws.tz, self_person_id=ws.self_person_id)
        for h in r.search(f"{ev.title} {ev.description or ''}", k=5, types={"document"}).hits:
            if all(x["ref"]["id"] != h.id for x in docs):
                docs.append({"ref": {"type": "document", "id": h.id}, "title": h.title, "authored_at": _iso(h.occurred_at),
                             "retrieved": True})
    health = None
    if ev.project_id:
        proj = db.get(m.Project, ev.project_id)
        if proj:
            ph = project_health(ws, proj)
            health = {"project": proj.name, "ref": {"type": "project", "id": proj.id}, "status": ph.status, "label": ph.label, "signals": ph.signals}
    return {
        "event": {"ref": {"type": "event", "id": ev.id}, "title": ev.title, "start_at": _iso(ev.start_at), "end_at": _iso(ev.end_at),
                  "description": ev.description, "location": ev.location},
        "participants": participants,
        "project": health,
        "recent_emails": [{"ref": {"type": "email", "id": e.id}, "subject": e.subject, "from": e.from_name or e.from_addr,
                           "sent_at": _iso(e.sent_at), "snippet": (e.body or "")[:200]} for e in emails],
        "open_commitments": [commitment_item(ws, c) for c in commitments],
        "decisions": [{"ref": {"type": "decision", "id": d.id}, "topic": d.topic, "chosen": d.chosen, "rejected": d.rejected,
                       "status": d.status, "decided_at": _iso(d.decided_at),
                       "evidence": [{"source_type": d.source_type, "source_id": d.source_id, "span": d.statement}]} for d in decisions],
        "related_documents": docs,
        "previous_meeting": {"ref": {"type": "event", "id": previous.id}, "title": previous.title,
                             "start_at": _iso(previous.start_at), "notes": previous.notes} if previous else None,
        "generated_at": now.isoformat(),
        "note": "Read-only brief. Nothing is sent or changed automatically.",
    }
