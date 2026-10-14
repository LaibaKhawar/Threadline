"""Dashboard, briefing, search, timeline, notifications and insights."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import rate_limit, workspace
from app.api.serialize import iso
from app.db import models as m
from app.ingestion.workspace import Workspace
from app.intelligence.briefs import daily_briefing
from app.retrieval.hybrid import HybridRetriever

router = APIRouter(prefix="/api", tags=["core"])


@router.get("/dashboard")
def dashboard(ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    db = ws.db
    brief = daily_briefing(ws)
    counts = {
        "emails": db.scalar(select(func.count()).select_from(m.Email).where(m.Email.user_id == ws.user_id)),
        "documents": db.scalar(select(func.count()).select_from(m.Document).where(m.Document.user_id == ws.user_id)),
        "meetings": db.scalar(select(func.count()).select_from(m.CalendarEvent).where(m.CalendarEvent.user_id == ws.user_id)),
        "people": db.scalar(select(func.count()).select_from(m.Person).where(m.Person.user_id == ws.user_id, m.Person.merged_into_id.is_(None))),
        "commitments_open": db.scalar(select(func.count()).select_from(m.Commitment).where(m.Commitment.user_id == ws.user_id, m.Commitment.status.in_(["OPEN", "OVERDUE"]))),
        "relationships": db.scalar(select(func.count()).select_from(m.Relationship).where(m.Relationship.user_id == ws.user_id, m.Relationship.status == "active")),
        "pending_inferences": db.scalar(select(func.count()).select_from(m.Inference).where(m.Inference.user_id == ws.user_id, m.Inference.status == "pending")),
        "merge_candidates": db.scalar(select(func.count()).select_from(m.MergeCandidate).where(m.MergeCandidate.user_id == ws.user_id, m.MergeCandidate.status == "pending")),
    }
    activity = [{"id": t.id, "kind": t.kind, "title": t.title, "occurred_at": iso(t.occurred_at), "ref": {"type": t.ref_type, "id": t.ref_id}}
                for t in db.scalars(select(m.TimelineEvent).where(m.TimelineEvent.user_id == ws.user_id, m.TimelineEvent.occurred_at <= ws.now())
                                    .order_by(m.TimelineEvent.occurred_at.desc()).limit(12))]
    me = db.get(m.Person, ws.self_person_id) if ws.self_person_id else None
    return {"now": ws.now().isoformat(), "clock_pinned": ws.settings.clock_override is not None,
            "user_first_name": me.display_name.split()[0] if me else None, "briefing": brief, "counts": counts, "recent_activity": activity}


@router.get("/briefing")
def briefing(ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    return daily_briefing(ws)


class BriefingConfig(BaseModel):
    sections: list[str]


@router.get("/briefing/config")
def get_briefing_config(ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    from app.intelligence.briefs import DEFAULT_SECTIONS

    return {"sections": (ws.settings.briefing_config or {}).get("sections") or DEFAULT_SECTIONS, "available": DEFAULT_SECTIONS}


@router.put("/briefing/config")
def set_briefing_config(body: BriefingConfig, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    ws.settings.briefing_config = {"sections": body.sections}
    ws.db.commit()
    return {"ok": True, "sections": body.sections}


@router.get("/search", dependencies=[Depends(rate_limit("search", 120))])
def search(q: str = Query(min_length=1, max_length=500), mode: str = Query("hybrid", pattern="^(hybrid|vector|keyword|graph)$"),
           types: str | None = None, k: int = Query(30, ge=1, le=100), ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    r = HybridRetriever(ws.db, ws.user_id, now=ws.now(), tz=ws.tz, self_person_id=ws.self_person_id)
    res = r.search(q, k=k, mode=mode, types=set(types.split(",")) if types else None)
    people = []
    for pid in res.query.person_ids:
        p = ws.db.get(m.Person, pid)
        if p:
            people.append({"type": "person", "id": p.id, "title": p.display_name, "snippet": p.primary_email or "", "channels": {"entity": 1}})
    projects = []
    for pid in res.query.project_ids:
        p2 = ws.db.get(m.Project, pid)
        if p2:
            projects.append({"type": "project", "id": p2.id, "title": p2.name, "snippet": p2.description or "", "channels": {"entity": 1}})
    groups = res.grouped()
    if people:
        groups["person"] = people
    if projects:
        groups["project"] = projects
    return {"query": res.query.as_dict(), "mode": mode, "timings_ms": res.timings_ms, "groups": groups,
            "results": [h.as_dict() for h in res.hits], "total": len(res.hits)}


@router.get("/timeline")
def timeline(start: datetime | None = None, end: datetime | None = None, project_id: str | None = None, person_id: str | None = None,
             kinds: str | None = None, limit: int = Query(200, le=1000), ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    q = select(m.TimelineEvent).where(m.TimelineEvent.user_id == ws.user_id, m.TimelineEvent.occurred_at <= (end or ws.now() + timedelta(days=60)))
    if start:
        q = q.where(m.TimelineEvent.occurred_at >= start)
    if project_id:
        q = q.where(m.TimelineEvent.project_id == project_id)
    if kinds:
        q = q.where(m.TimelineEvent.kind.in_(kinds.split(",")))
    rows = list(ws.db.scalars(q.order_by(m.TimelineEvent.occurred_at.desc()).limit(limit * 2)))
    if person_id:
        rows = [r for r in rows if person_id in (r.person_ids or [])]
    projects = {p.id: {"id": p.id, "name": p.name, "color": p.color} for p in ws.db.scalars(select(m.Project).where(m.Project.user_id == ws.user_id))}
    return {"events": [{"id": r.id, "occurred_at": iso(r.occurred_at), "kind": r.kind, "title": r.title, "detail": r.detail,
                        "ref": {"type": r.ref_type, "id": r.ref_id}, "project": projects.get(r.project_id or ""),
                        "future": r.occurred_at > ws.now()} for r in rows[:limit]]}


@router.get("/notifications")
def notifications(unread_only: bool = False, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    q = select(m.Notification).where(m.Notification.user_id == ws.user_id)
    if unread_only:
        q = q.where(m.Notification.read_at.is_(None))
    rows = list(ws.db.scalars(q.order_by(m.Notification.created_at.desc()).limit(100)))
    unread = ws.db.scalar(select(func.count()).select_from(m.Notification).where(m.Notification.user_id == ws.user_id, m.Notification.read_at.is_(None)))
    return {"unread": unread, "items": [{"id": n.id, "category": n.category, "title": n.title, "body": n.body, "score": n.score,
                                         "ref": {"type": n.ref_type, "id": n.ref_id}, "insight_id": n.insight_id,
                                         "read": n.read_at is not None, "created_at": iso(n.created_at)} for n in rows],
            "categories": _categories(ws)}


def _categories(ws: Workspace) -> list[dict[str, Any]]:
    from app.intelligence.proactive import CATEGORIES

    prefs = ws.settings.notification_prefs or {}
    return [{"key": k, "label": v, "enabled": prefs.get(k, True)} for k, v in CATEGORIES.items()]


@router.post("/notifications/{nid}/read")
def mark_read(nid: str, ws: Workspace = Depends(workspace)) -> dict[str, bool]:
    n = ws.db.get(m.Notification, nid)
    if not n or n.user_id != ws.user_id:
        raise HTTPException(404, "not found")
    n.read_at = ws.now()
    ws.db.commit()
    return {"ok": True}


@router.post("/notifications/read-all")
def mark_all_read(ws: Workspace = Depends(workspace)) -> dict[str, bool]:
    for n in ws.db.scalars(select(m.Notification).where(m.Notification.user_id == ws.user_id, m.Notification.read_at.is_(None))):
        n.read_at = ws.now()
    ws.db.commit()
    return {"ok": True}


class NotificationPrefs(BaseModel):
    prefs: dict[str, bool]


@router.put("/notifications/preferences")
def set_prefs(body: NotificationPrefs, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    ws.settings.notification_prefs = {**(ws.settings.notification_prefs or {}), **body.prefs}
    ws.db.commit()
    return {"categories": _categories(ws)}


@router.get("/insights")
def insights(kind: str | None = None, status: str = "open", ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    q = select(m.Insight).where(m.Insight.user_id == ws.user_id, m.Insight.status == status)
    if kind:
        q = q.where(m.Insight.kind.in_(kind.split(",")))
    rows = list(ws.db.scalars(q.order_by(m.Insight.score.desc()).limit(100)))
    return {"items": [{"id": i.id, "kind": i.kind, "title": i.title, "explanation": i.explanation, "evidence": i.evidence,
                       "confidence": i.confidence, "importance": i.importance, "urgency": i.urgency, "score": i.score,
                       "ref": {"type": i.ref_type, "id": i.ref_id}, "suggested_action": i.suggested_action, "feedback": i.feedback,
                       "status": i.status, "created_at": iso(i.created_at)} for i in rows]}


class InsightFeedback(BaseModel):
    feedback: str | None = None  # useful | not_useful
    status: str | None = None  # dismissed | resolved | snoozed | open


@router.post("/insights/{iid}")
def insight_feedback(iid: str, body: InsightFeedback, ws: Workspace = Depends(workspace)) -> dict[str, bool]:
    i = ws.db.get(m.Insight, iid)
    if not i or i.user_id != ws.user_id:
        raise HTTPException(404, "not found")
    if body.feedback in ("useful", "not_useful"):
        i.feedback = body.feedback
    if body.status in ("dismissed", "resolved", "snoozed", "open"):
        i.status = body.status
    ws.db.add(m.AuditLog(user_id=ws.user_id, actor="user", action="insight_feedback", target_type="insight", target_id=i.id,
                         details={"feedback": body.feedback, "status": body.status}))
    ws.db.commit()
    return {"ok": True}
