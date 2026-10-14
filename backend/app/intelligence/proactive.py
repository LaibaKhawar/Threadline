"""Proactive intelligence: detectors -> insights -> ranked, rate-limited notifications.

Every insight carries its evidence (source references + exact text) and an explanation sentence.
Ranking:  score = (0.35*importance + 0.30*urgency + 0.20*confidence + 0.15*recency) * feedback(kind)
where feedback(kind) shrinks kinds the user keeps marking "not useful" (Laplace-smoothed ratio).
Notifications are created only for the top-scoring new insights above a threshold, per enabled
category, with a per-run cap, so the system does not become a notification firehose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.timeutil import ensure_aware
from app.db import models as m
from app.extraction.text import stable_hash, strip_quoted_reply
from app.ingestion.workspace import Workspace

NOTIFY_THRESHOLD = 0.55
MAX_NOTIFICATIONS_PER_RUN = 5
CATEGORIES = {
    "overdue_commitment": "Overdue commitments",
    "my_overdue_commitment": "Your overdue promises",
    "awaiting_my_reply": "People awaiting your reply",
    "unanswered_request": "Unanswered requests",
    "deadline_soon": "Upcoming deadlines",
    "overdue_task": "Overdue tasks",
    "meeting_prep": "Meetings with unresolved items",
    "stalled_project": "Stalled projects",
    "decision_changed": "Changed decisions",
    "blocked": "Blocked work",
    "possible_fulfillment": "Possible fulfilments to confirm",
}


@dataclass
class Draft:
    kind: str
    title: str
    explanation: str
    evidence: list[dict[str, Any]]
    confidence: float
    importance: float
    urgency: float
    occurred_at: datetime
    ref: tuple[str, str] | None = None
    project_id: str | None = None
    person_id: str | None = None
    suggested_action: dict[str, Any] = field(default_factory=dict)
    key_parts: tuple[Any, ...] = ()


def ev(source_type: str, source_id: str, span: str | None, label: str | None = None, at: datetime | None = None) -> dict[str, Any]:
    return {"source_type": source_type, "source_id": source_id, "span": (span or "")[:400], "label": label,
            "at": at.isoformat() if at else None}


def _name(db: Session, pid: str | None, ws: Workspace | None = None) -> str:
    if ws and pid and pid == ws.self_person_id:
        return "you"
    p = db.get(m.Person, pid) if pid else None
    return p.display_name if p else "someone"


def _d(dt: datetime) -> str:
    return dt.strftime("%b %d, %Y").replace(" 0", " ")


def _days(a: datetime, b: datetime) -> int:
    return max(0, int((a - b).total_seconds() // 86400))


def _source_label(db: Session, st: str, sid: str) -> str:
    if st == "email":
        e = db.get(m.Email, sid)
        return f"Email “{e.subject}” ({e.sent_at.date().isoformat()})" if e else "Email"
    if st == "event":
        e2 = db.get(m.CalendarEvent, sid)
        return f"Meeting “{e2.title}” ({e2.start_at.date().isoformat()})" if e2 else "Meeting"
    if st == "document":
        d = db.get(m.Document, sid)
        return f"Document “{d.title}”" if d else "Document"
    if st == "note":
        n = db.get(m.Note, sid)
        return f"Note “{n.title}”" if n else "Note"
    return st


# =============================================================================== detectors


def detect_commitments(ws: Workspace) -> list[Draft]:
    db, now = ws.db, ws.now()
    out: list[Draft] = []
    rows = db.scalars(select(m.Commitment).where(m.Commitment.user_id == ws.user_id,
                                                 m.Commitment.status.in_(["OPEN", "OVERDUE"])))
    for c in rows:
        due = ensure_aware(c.due_at)
        mine = c.actor_person_id is not None and c.actor_person_id == ws.self_person_id
        evid = [ev(c.source_type, c.source_id, c.evidence_span, _source_label(db, c.source_type, c.source_id), c.detected_at)]
        if c.status == "OVERDUE" and due:
            late = _days(now, due)
            if mine:
                out.append(Draft("my_overdue_commitment", f"You promised to {c.action} {c.object or ''}".strip() + f" by {_d(due)}",
                                 f"You committed to this {late} day(s) ago past its due date and no later message from you appears to deliver it. "
                                 + (c.resolution_reason or ""), evid, c.confidence, 0.8, min(1.0, 0.6 + late * 0.05), due,
                                 ("commitment", c.id), c.project_id, c.recipient_person_id,
                                 {"type": "draft_followup", "to_person_id": c.recipient_person_id}, ("c", c.id)))
            else:
                who = _name(db, c.actor_person_id, ws)
                out.append(Draft("overdue_commitment",
                                 f"Possible overdue commitment: {who} was expected to {c.action} {c.object or 'this'} by {_d(due)}",
                                 c.resolution_reason or "The due date passed with no matching delivery.", evid, c.confidence * 0.95,
                                 0.75, min(1.0, 0.55 + late * 0.05), due, ("commitment", c.id), c.project_id, c.actor_person_id,
                                 {"type": "draft_followup", "to_person_id": c.actor_person_id}, ("c", c.id)))
        elif due and now <= due <= now + timedelta(days=2):
            hours = (due - now).total_seconds() / 3600
            who = "You" if mine else _name(db, c.actor_person_id, ws)
            out.append(Draft("deadline_soon", f"{who} {'have' if mine else 'has'} to {c.action} {c.object or ''} by {due.strftime('%a %b %d')}".replace("  ", " "),
                             f"Due in {max(0, int(hours))} hours. Detected in {_source_label(db, c.source_type, c.source_id)}.",
                             evid, c.confidence, 0.65 if mine else 0.5, 0.9 if hours < 24 else 0.7, c.detected_at,
                             ("commitment", c.id), c.project_id, c.actor_person_id, key_parts=("soon", c.id)))
        if c.resolution_source_id and c.resolution_confidence and c.status in ("OPEN", "OVERDUE") and c.resolution_confidence >= 0.45:
            out.append(Draft("possible_fulfillment", f"Did {_name(db, c.actor_person_id, ws)} fulfil: {c.description}?",
                             c.resolution_reason or "", [*evid, ev(c.resolution_source_type or "email", c.resolution_source_id,
                                                                   None, _source_label(db, c.resolution_source_type or "email", c.resolution_source_id))],
                             c.resolution_confidence, 0.45, 0.4, now, ("commitment", c.id), c.project_id, c.actor_person_id,
                             {"type": "confirm_fulfillment", "commitment_id": c.id}, ("pf", c.id, c.resolution_source_id)))
    return out


_QUESTION = re.compile(r"\?|\b(can you|could you|would you|let me know|thoughts|what do you think|any update)\b", re.I)


def detect_threads(ws: Workspace) -> list[Draft]:
    """Awaiting my reply / my unanswered requests, judged at thread level."""
    db, now = ws.db, ws.now()
    out: list[Draft] = []
    if not ws.self_person_id:
        return out
    threads = db.scalars(select(m.EmailThread).where(m.EmailThread.user_id == ws.user_id,
                                                     m.EmailThread.last_at >= now - timedelta(days=45)))
    for t in threads:
        msgs = list(db.scalars(select(m.Email).where(m.Email.thread_id == t.id, m.Email.sent_at <= now).order_by(m.Email.sent_at)))
        if not msgs:
            continue
        last = msgs[-1]
        body = strip_quoted_reply(last.body or "")
        age = _days(now, last.sent_at)
        if last.direction == "inbound" and _QUESTION.search(body):
            to_me = any((r.get("email") or "").lower() in ws.self_emails for r in (last.to_addrs or []))
            if to_me and age >= 1:
                t.awaiting = "me"
                who = last.from_name or last.from_addr
                q = next((s for s in re.split(r"(?<=[.?!])\s+", body) if _QUESTION.search(s)), body[:200])
                asks_me = db.scalar(select(func.count()).select_from(m.Commitment).where(
                    m.Commitment.source_id == last.id, m.Commitment.kind == "request",
                    m.Commitment.actor_person_id == ws.self_person_id)) or 0
                importance = 0.45 + (0.2 if last.project_id else 0.0) + (0.15 if asks_me else 0.0)
                out.append(Draft("awaiting_my_reply", f"{who} may be waiting for your reply: “{t.subject}”",
                                 f"Their message {age} day(s) ago asks: “{q.strip()[:200]}” and you have not replied in this thread since.",
                                 [ev("email", last.id, q, _source_label(db, "email", last.id), last.sent_at)],
                                 0.75, importance, min(1.0, 0.4 + age * 0.08), last.sent_at, ("email", last.id), last.project_id,
                                 last.sender_person_id, {"type": "draft_reply", "email_id": last.id}, ("await", t.id, last.id)))
                continue
        if last.direction == "outbound" and age >= 3:
            reqs = list(db.scalars(select(m.Commitment).where(m.Commitment.source_id == last.id, m.Commitment.kind == "request",
                                                              m.Commitment.status.in_(["OPEN", "OVERDUE"]))))
            if reqs or _QUESTION.search(body):
                r = reqs[0] if reqs else None
                target = r.actor_person_id if r else (db.scalar(select(m.Relationship.dst_id).where(
                    m.Relationship.src_id == last.id, m.Relationship.rel_type == "SENT_TO").limit(1)))
                who = _name(db, target, ws)
                what = f"{r.action} {r.object or ''}".strip() if r else "a response"
                t.awaiting = "them"
                out.append(Draft("unanswered_request", f"Potential follow-up: {who} hasn't responded about {what}",
                                 f"You asked {who} {age} days ago (“{(r.evidence_span if r else body[:160]).strip()[:200]}”) and no later email in the thread appears to contain a reply.",
                                 [ev("email", last.id, r.evidence_span if r else body[:200], _source_label(db, "email", last.id), last.sent_at)],
                                 0.7, 0.65 if r and r.action in ("approve", "sign") else 0.55, min(1.0, 0.3 + age * 0.07),
                                 last.sent_at, ("email", last.id), last.project_id, target,
                                 {"type": "draft_followup", "to_person_id": target, "email_id": last.id}, ("unans", t.id, last.id)))
        else:
            if t.awaiting and last.direction == "outbound":
                t.awaiting = None
    return out


def detect_tasks(ws: Workspace) -> list[Draft]:
    db, now = ws.db, ws.now()
    out = []
    for t in db.scalars(select(m.Task).where(m.Task.user_id == ws.user_id, m.Task.status.in_(["active", "blocked"]))):
        due = ensure_aware(t.due_at)
        evid = [ev(t.source_type, t.source_id, t.evidence_span, _source_label(db, t.source_type, t.source_id))] if t.source_id and t.source_type else []
        if due and due < now:
            out.append(Draft("overdue_task", f"Overdue task: {t.title}", f"Due {_d(due)} ({_days(now, due)} days ago) and still {t.status}.",
                             evid, 1.0, 0.6, min(1.0, 0.6 + _days(now, due) * 0.05), due, ("task", t.id), t.project_id,
                             key_parts=("ot", t.id)))
        if t.status == "blocked":
            who = _name(db, t.blocked_by_person_id, ws) if t.blocked_by_person_id else "an unknown blocker"
            out.append(Draft("blocked", f"Blocked: {t.title}", f"Blocked by {who}. {t.blocked_reason or ''}".strip(), evid, 0.8, 0.55, 0.5,
                             t.updated_at or now, ("task", t.id), t.project_id, t.blocked_by_person_id, key_parts=("bl", t.id)))
    return out


def detect_meetings(ws: Workspace) -> list[Draft]:
    db, now = ws.db, ws.now()
    out = []
    upcoming = db.scalars(select(m.CalendarEvent).where(m.CalendarEvent.user_id == ws.user_id, m.CalendarEvent.start_at >= now,
                                                         m.CalendarEvent.start_at <= now + timedelta(days=1)))
    for e in upcoming:
        people = [p for p in db.scalars(select(m.EventParticipant.person_id).where(m.EventParticipant.event_id == e.id)) if p != ws.self_person_id]
        if not people:
            continue
        q = select(m.Commitment).where(m.Commitment.user_id == ws.user_id, m.Commitment.status.in_(["OPEN", "OVERDUE"]),
                                       (m.Commitment.actor_person_id.in_(people)) | (m.Commitment.recipient_person_id.in_(people)))
        if e.project_id:
            q = q.where((m.Commitment.project_id == e.project_id) | m.Commitment.project_id.is_(None))
        open_c = list(db.scalars(q))
        if not open_c:
            continue
        hours = (ensure_aware(e.start_at) - now).total_seconds() / 3600  # type: ignore[operator]
        out.append(Draft("meeting_prep", f"“{e.title}” in {max(0, int(hours))}h has {len(open_c)} unresolved item(s)",
                         "Open commitments involving attendees: " + "; ".join(c.description for c in open_c[:3]),
                         [ev(c.source_type, c.source_id, c.evidence_span, _source_label(db, c.source_type, c.source_id)) for c in open_c[:3]],
                         0.85, 0.6, 0.9 if hours < 3 else 0.7, now, ("event", e.id), e.project_id,
                         suggested_action={"type": "meeting_brief", "event_id": e.id}, key_parts=("mp", e.id)))
    return out


def detect_decisions(ws: Workspace) -> list[Draft]:
    db, now = ws.db, ws.now()
    out = []
    for d in db.scalars(select(m.Decision).where(m.Decision.user_id == ws.user_id, m.Decision.status == "superseded",
                                                 m.Decision.superseded_by_id.is_not(None))):
        new = db.get(m.Decision, d.superseded_by_id)
        if not new or _days(now, ensure_aware(new.decided_at)) > 21:  # type: ignore[arg-type]
            continue
        out.append(Draft("decision_changed", f"Decision changed ({d.topic}): {d.chosen} → {new.chosen}",
                         f"On {_d(new.decided_at)} the {d.topic} decision changed from {d.chosen} "
                         f"(decided {_d(d.decided_at)}) to {new.chosen}.",
                         [ev(new.source_type, new.source_id, new.statement, _source_label(db, new.source_type, new.source_id), new.decided_at),
                          ev(d.source_type, d.source_id, d.statement, _source_label(db, d.source_type, d.source_id), d.decided_at)],
                         min(d.confidence, new.confidence), 0.6, 0.4, new.decided_at, ("decision", new.id), new.project_id,
                         key_parts=("dc", d.id, new.id)))
    return out


@dataclass
class Health:
    status: str  # on_track | attention | at_risk
    label: str
    score: float
    signals: list[dict[str, Any]]


def project_health(ws: Workspace, project: m.Project) -> Health:
    """Heuristic, explained: each signal and its weight is returned so the UI can show 'why'."""
    db, now = ws.db, ws.now()
    signals: list[dict[str, Any]] = []
    risk = 0.0
    overdue_c = db.scalar(select(func.count()).select_from(m.Commitment).where(
        m.Commitment.user_id == ws.user_id, m.Commitment.project_id == project.id, m.Commitment.status == "OVERDUE")) or 0
    if overdue_c:
        risk += 0.25 * min(overdue_c, 3)
        signals.append({"signal": f"{overdue_c} overdue commitment(s)", "weight": round(0.25 * min(overdue_c, 3), 2)})
    tasks = list(db.scalars(select(m.Task).where(m.Task.user_id == ws.user_id, m.Task.project_id == project.id, m.Task.status.in_(["active", "blocked"]))))
    overdue_t = [t for t in tasks if t.due_at and ensure_aware(t.due_at) < now]  # type: ignore[operator]
    blocked = [t for t in tasks if t.status == "blocked"]
    blocked_edges = db.scalar(select(func.count()).select_from(m.Relationship).where(
        m.Relationship.user_id == ws.user_id, m.Relationship.src_type == "project", m.Relationship.src_id == project.id,
        m.Relationship.rel_type == "BLOCKED_BY", m.Relationship.status == "active")) or 0
    if overdue_t:
        risk += 0.15 * min(len(overdue_t), 3)
        signals.append({"signal": f"{len(overdue_t)} overdue task(s)", "weight": round(0.15 * min(len(overdue_t), 3), 2)})
    if blocked or blocked_edges:
        n = len(blocked) + blocked_edges
        risk += 0.2 * min(n, 2)
        signals.append({"signal": f"{n} blocker(s) reported", "weight": round(0.2 * min(n, 2), 2)})
    last = db.scalar(select(func.max(m.TimelineEvent.occurred_at)).where(m.TimelineEvent.user_id == ws.user_id, m.TimelineEvent.project_id == project.id,
                                                                          m.TimelineEvent.occurred_at <= now))
    last_email = db.scalar(select(func.max(m.Email.sent_at)).where(m.Email.user_id == ws.user_id, m.Email.project_id == project.id, m.Email.sent_at <= now))
    last_activity = max(filter(None, [ensure_aware(last), ensure_aware(last_email)]), default=None)
    if last_activity:
        idle = _days(now, last_activity)
        if idle >= 7:
            w = min(0.3, 0.03 * idle)
            risk += w
            signals.append({"signal": f"No activity for {idle} days", "weight": round(w, 2)})
    else:
        signals.append({"signal": "No activity recorded yet", "weight": 0})
    soon = db.scalar(select(func.count()).select_from(m.Commitment).where(
        m.Commitment.user_id == ws.user_id, m.Commitment.project_id == project.id, m.Commitment.status == "OPEN",
        m.Commitment.due_at <= now + timedelta(days=3), m.Commitment.due_at >= now)) or 0
    if soon:
        risk += 0.05 * soon
        signals.append({"signal": f"{soon} deadline(s) in the next 3 days", "weight": round(0.05 * soon, 2)})
    open_tasks = len(tasks)
    signals.append({"signal": f"{open_tasks} open task(s)", "weight": 0})
    risk = round(min(risk, 1.0), 2)
    status, label = ("at_risk", "At Risk") if risk >= 0.6 else (("attention", "Attention Needed") if risk >= 0.25 else ("on_track", "On Track"))
    if project.status_manual:
        label_map = {"on_track": "On Track", "attention": "Attention Needed", "at_risk": "At Risk", "done": "Done", "paused": "Paused"}
        signals.insert(0, {"signal": f"Status set manually to {label_map.get(project.status_manual, project.status_manual)} (overrides the heuristic)", "weight": 0})
        return Health(project.status_manual, label_map.get(project.status_manual, project.status_manual), risk, signals)
    return Health(status, label, risk, signals)


def detect_projects(ws: Workspace) -> list[Draft]:
    out = []
    for p in ws.db.scalars(select(m.Project).where(m.Project.user_id == ws.user_id, m.Project.archived.is_(False))):
        h = project_health(ws, p)
        if h.status in ("at_risk", "attention"):
            why = "; ".join(s["signal"] for s in h.signals if s["weight"])
            out.append(Draft("stalled_project", f"{p.name} needs attention ({h.label})", f"Signals: {why}.", [], 0.7,
                             0.7 if h.status == "at_risk" else 0.5, min(1.0, h.score), ws.now(), ("project", p.id), p.id,
                             key_parts=("ph", p.id, h.status)))
    return out


# =============================================================================== ranking + persistence


def feedback_factor(db: Session, user_id: str, kind: str) -> float:
    rows = db.execute(select(m.Insight.feedback, func.count()).where(
        m.Insight.user_id == user_id, m.Insight.kind == kind, m.Insight.feedback.is_not(None)).group_by(m.Insight.feedback)).all()
    counts = {f: n for f, n in rows}
    useful, not_useful = counts.get("useful", 0), counts.get("not_useful", 0)
    return round(min(1.2, max(0.3, 2 * (useful + 1) / (useful + not_useful + 2))), 3)


def rank(d: Draft, now: datetime, factor: float) -> float:
    age_days = max(0.0, (now - ensure_aware(d.occurred_at)).total_seconds() / 86400)  # type: ignore[operator]
    recency = max(0.0, 1.0 - age_days / 30)
    base = 0.35 * d.importance + 0.30 * d.urgency + 0.20 * d.confidence + 0.15 * recency
    return round(base * factor, 4)


def run_proactive(ws: Workspace) -> dict[str, int]:
    db, now = ws.db, ws.now()
    drafts = detect_commitments(ws) + detect_threads(ws) + detect_tasks(ws) + detect_meetings(ws) + detect_decisions(ws) + detect_projects(ws)
    factors: dict[str, float] = {}
    seen_keys: set[str] = set()
    new_insights: list[m.Insight] = []
    for d in drafts:
        factors.setdefault(d.kind, feedback_factor(db, ws.user_id, d.kind))
        key = stable_hash(ws.user_id, d.kind, *d.key_parts) if d.key_parts else stable_hash(ws.user_id, d.kind, d.title)
        seen_keys.add(key)
        score = rank(d, now, factors[d.kind])
        row = db.scalar(select(m.Insight).where(m.Insight.user_id == ws.user_id, m.Insight.dedupe_key == key))
        if row is None:
            row = m.Insight(user_id=ws.user_id, kind=d.kind, dedupe_key=key, status="open", title=d.title, explanation=d.explanation,
                            evidence=d.evidence, confidence=d.confidence, importance=d.importance, urgency=d.urgency, score=score,
                            ref_type=d.ref[0] if d.ref else None, ref_id=d.ref[1] if d.ref else None, project_id=d.project_id,
                            person_id=d.person_id, suggested_action=d.suggested_action)
            db.add(row)
            new_insights.append(row)
        else:
            row.title, row.explanation, row.evidence, row.score = d.title, d.explanation, d.evidence, score
            row.urgency, row.confidence = d.urgency, d.confidence
            if row.status == "resolved":
                row.status = "open"
    # Insights whose condition no longer holds resolve themselves.
    for row in db.scalars(select(m.Insight).where(m.Insight.user_id == ws.user_id, m.Insight.status == "open")):
        if row.dedupe_key not in seen_keys:
            row.status = "resolved"
    db.flush()
    prefs = ws.settings.notification_prefs or {}
    created = 0
    for ins in sorted(new_insights, key=lambda i: -i.score):
        if created >= MAX_NOTIFICATIONS_PER_RUN or ins.score < NOTIFY_THRESHOLD:
            continue
        if prefs.get(ins.kind) is False:
            continue
        nkey = stable_hash(ws.user_id, "notif", ins.dedupe_key)
        if db.scalar(select(m.Notification.id).where(m.Notification.user_id == ws.user_id, m.Notification.dedupe_key == nkey)):
            continue
        db.add(m.Notification(user_id=ws.user_id, category=ins.kind, title=ins.title, body=ins.explanation[:600],
                              ref_type=ins.ref_type, ref_id=ins.ref_id, insight_id=ins.id, score=ins.score, dedupe_key=nkey))
        created += 1
    return {"insights": len(drafts), "new": len(new_insights), "notifications": created}
