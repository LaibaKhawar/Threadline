"""Event handlers: the event-driven processing chain (see app.domain.events)."""

from __future__ import annotations

from typing import cast

from sqlalchemy.orm import Session

from app.commitments.resolution import resolve_commitments
from app.db import models as m
from app.domain.events import (
    CONTENT_PROCESSED,
    SOURCE_ITEM_DELETED,
    SOURCE_ITEM_UPSERTED,
    SYNC_COMPLETED,
    handles,
    publish,
)
from app.ingestion.processor import process_source_item
from app.ingestion.purge import purge_source_item
from app.ingestion.workspace import Workspace
from app.intelligence.proactive import run_proactive


@handles(SOURCE_ITEM_UPSERTED)
def on_source_item(db: Session, ev: m.DomainEvent) -> None:
    sid = ev.payload["source_item_id"]
    process_source_item(db, sid)
    publish(db, ev.user_id, CONTENT_PROCESSED, {"source_item_id": sid})
    db.commit()


@handles(CONTENT_PROCESSED)
def on_content_processed(db: Session, ev: m.DomainEvent) -> None:
    """Cheap incremental check: does this new item fulfil an open promise by its author?"""
    si = db.get(m.SourceItem, ev.payload["source_item_id"])
    if si is None or si.kind not in ("email", "document", "event"):
        return
    content_models: dict[str, m.ContentModel] = {"email": m.Email, "document": m.Document, "event": m.CalendarEvent}
    model = content_models[si.kind]
    row = cast("m.ContentRow | None", db.query(model).filter(model.source_item_id == si.id).first())
    if row is None:
        return
    author = getattr(row, "sender_person_id", None) or getattr(row, "author_person_id", None)
    if author:
        resolve_commitments(Workspace(db, ev.user_id), actor_pid=author, only_source=(si.kind, str(row.id)))
    db.commit()


@handles(SYNC_COMPLETED)
def on_sync_completed(db: Session, ev: m.DomainEvent) -> None:
    ws = Workspace(db, ev.user_id)
    resolve_commitments(ws)
    db.flush()
    run_proactive(ws)
    ws.memory.consolidate(ws.now())
    db.commit()


@handles(SOURCE_ITEM_DELETED)
def on_source_deleted(db: Session, ev: m.DomainEvent) -> None:
    si = db.get(m.SourceItem, ev.payload["source_item_id"])
    if si is not None:
        purge_source_item(db, si)
    db.commit()
