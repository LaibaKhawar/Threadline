"""Plain dict serialisers for API responses (secrets never included)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db import models as m


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def person_brief(db: Session, pid: str | None) -> dict[str, Any] | None:
    if not pid:
        return None
    p = db.get(m.Person, pid)
    if not p:
        return None
    return {"id": p.id, "name": p.display_name, "email": p.primary_email, "is_self": p.is_self}


def project_brief(db: Session, pid: str | None) -> dict[str, Any] | None:
    if not pid:
        return None
    p = db.get(m.Project, pid)
    return {"id": p.id, "name": p.name, "color": p.color} if p else None


def email_dict(db: Session, e: m.Email, *, full: bool = False) -> dict[str, Any]:
    d = {"id": e.id, "thread_id": e.thread_id, "subject": e.subject, "from_addr": e.from_addr, "from_name": e.from_name,
         "to": e.to_addrs, "cc": e.cc_addrs, "sent_at": iso(e.sent_at), "direction": e.direction,
         "attachments": e.attachments, "project": project_brief(db, e.project_id), "importance": e.importance,
         "sender": ({**pb, "email": e.from_addr} if (pb := person_brief(db, e.sender_person_id)) else None), "snippet": (e.body or "")[:220]}
    if full:
        d["body"] = e.body
    return d


def event_dict(db: Session, e: m.CalendarEvent) -> dict[str, Any]:
    return {"id": e.id, "title": e.title, "description": e.description, "location": e.location, "start_at": iso(e.start_at),
            "end_at": iso(e.end_at), "attendees": e.attendees, "organizer": e.organizer, "notes": e.notes,
            "project": project_brief(db, e.project_id), "status": e.status}


def document_dict(db: Session, d: m.Document, *, full: bool = False) -> dict[str, Any]:
    out = {"id": d.id, "title": d.title, "filename": d.original_filename, "mime_type": d.mime_type, "size_bytes": d.size_bytes,
           "page_count": d.page_count, "status": d.status, "error": d.error, "project": project_brief(db, d.project_id),
           "author": person_brief(db, d.author_person_id), "authored_at": iso(d.authored_at), "created_at": iso(d.created_at),
           "metadata": {k: v for k, v in (d.doc_metadata or {}).items() if k in ("author", "columns", "row_count", "sheets")}}
    if full:
        out["text"] = d.text
    return out


def note_dict(db: Session, n: m.Note) -> dict[str, Any]:
    return {"id": n.id, "title": n.title, "body": n.body, "tags": n.tags, "ai_annotations": n.ai_annotations,
            "project": project_brief(db, n.project_id), "pinned": n.pinned, "created_at": iso(n.created_at),
            "updated_at": iso(n.updated_at)}


def task_dict(db: Session, t: m.Task) -> dict[str, Any]:
    return {"id": t.id, "title": t.title, "description": t.description, "project": project_brief(db, t.project_id),
            "owner": person_brief(db, t.owner_person_id), "status": t.status, "priority": t.priority, "due_at": iso(t.due_at),
            "blocked_by": person_brief(db, t.blocked_by_person_id), "blocked_reason": t.blocked_reason,
            "source": {"type": t.source_type, "id": t.source_id, "span": t.evidence_span} if t.source_id else None,
            "confidence": t.confidence, "manually_created": t.manually_created, "ai_suggested": t.ai_suggested,
            "created_at": iso(t.created_at), "completed_at": iso(t.completed_at)}


def commitment_dict(db: Session, c: m.Commitment) -> dict[str, Any]:
    return {"id": c.id, "kind": c.kind, "description": c.description, "action": c.action, "object": c.object,
            "actor": person_brief(db, c.actor_person_id), "actor_text": c.actor_text, "recipient": person_brief(db, c.recipient_person_id),
            "status": c.status, "confidence": c.confidence, "extractor": c.extractor, "due_at": iso(c.due_at), "due_text": c.due_text,
            "detected_at": iso(c.detected_at), "project": project_brief(db, c.project_id),
            "source": {"type": c.source_type, "id": c.source_id, "span": c.evidence_span, "start": c.span_start, "end": c.span_end},
            "resolution": {"type": c.resolution_source_type, "id": c.resolution_source_id, "confidence": c.resolution_confidence,
                           "reason": c.resolution_reason, "resolved_at": iso(c.resolved_at)} if c.resolution_reason else None,
            "user_confirmed": c.user_confirmed, "user_modified": c.user_modified}


def decision_dict(db: Session, d: m.Decision) -> dict[str, Any]:
    return {"id": d.id, "topic": d.topic, "chosen": d.chosen, "rejected": d.rejected, "statement": d.statement,
            "decided_at": iso(d.decided_at), "status": d.status, "superseded_by_id": d.superseded_by_id,
            "project": project_brief(db, d.project_id), "confidence": d.confidence,
            "source": {"type": d.source_type, "id": d.source_id, "span": d.evidence_span},
            "participants": [x for x in (person_brief(db, p) for p in d.participants or []) if x], "user_confirmed": d.user_confirmed}


def integration_dict(i: m.Integration, state: m.SyncState | None = None) -> dict[str, Any]:
    return {"id": i.id, "kind": i.kind, "name": i.name, "status": i.status,
            "config": {k: v for k, v in (i.config or {}).items() if not k.startswith("_") and "secret" not in k.lower() and "token" not in k.lower()},
            "store_locally": i.store_locally, "local_ai_allowed": i.local_ai_allowed, "cloud_ai_allowed": i.cloud_ai_allowed,
            "last_sync_at": iso(i.last_sync_at), "last_error": i.last_error, "created_at": iso(i.created_at),
            "sync": {"cursor_present": bool(state.cursor) if state else False, "last_completed_at": iso(state.last_completed_at) if state else None,
                     "items_created": state.items_created if state else 0, "items_updated": state.items_updated if state else 0,
                     "items_deleted": state.items_deleted if state else 0, "items_unchanged": state.items_unchanged if state else 0,
                     "error_count": state.error_count if state else 0, "rate_limit_remaining": state.rate_limit_remaining if state else None}}
