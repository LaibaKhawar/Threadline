"""Sync engine: runs a connector, upserts source items idempotently, publishes domain events.

* Deterministic identity: (user, integration, external_id) is unique.
* Change detection: content hash; unchanged items are counted and skipped.
* Checkpointing: progress is committed every CHECKPOINT_EVERY items, so an interrupted sync resumes
  without duplicating work (already-stored hashes are skipped on the next run).
* Deletions: tombstoned (deleted_at) and their derived data purged via SourceItemDeleted.
* Errors: recorded on the sync state and integration; retryable errors propagate to the worker,
  which retries with exponential backoff.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.base import (
    ConnectorError,
    Deletion,
    Normalized,
    NormalizedDocument,
    NormalizedEmail,
    NormalizedEvent,
    NormalizedNote,
    SyncContext,
    content_hash,
)
from app.connectors.registry import get_connector
from app.core.config import get_settings
from app.core.crypto import decrypt_json, encrypt_json
from app.core.logging import get_logger
from app.core.metrics import SYNC_ITEMS
from app.core.timeutil import utcnow
from app.db import models as m
from app.documents.service import store_document_bytes
from app.domain.events import SOURCE_ITEM_DELETED, SOURCE_ITEM_UPSERTED, SYNC_COMPLETED, dispatch, publish

log = get_logger(__name__)
CHECKPOINT_EVERY = 25


@dataclass
class SyncReport:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    deleted: int = 0
    errors: list[str] = field(default_factory=list)
    seconds: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def run_sync(db: Session, integration_id: str, *, dispatch_events: bool = True) -> SyncReport:
    integ = db.get(m.Integration, integration_id)
    if integ is None:
        raise ValueError("integration not found")
    if integ.status == "revoked":
        raise ConnectorError("integration is disconnected", retryable=False)
    if not integ.store_locally:
        raise ConnectorError("storage is disabled for this source in the Privacy Center", retryable=False)
    state = db.scalar(select(m.SyncState).where(m.SyncState.integration_id == integ.id))
    if state is None:
        state = m.SyncState(integration_id=integ.id, checkpoint={})
        db.add(state)
        db.flush()
    cred = db.scalar(select(m.Credential).where(m.Credential.integration_id == integ.id))
    credentials = decrypt_json(cred.ciphertext) if cred else None
    cls = get_connector(integ.kind)
    config = dict(integ.config or {})
    s = get_settings()
    if integ.kind == "local_files":
        config["_allowed_roots"] = list(s.local_import_roots)
        config["_forbidden_roots"] = [s.data_dir]
    if integ.kind in ("gmail", "gcal"):
        config.update({"client_id": s.google_client_id, "client_secret": s.google_client_secret})
    connector = cls(config, credentials)
    report = SyncReport()
    t0 = time.perf_counter()
    state.last_started_at = utcnow()
    integ.status = "syncing"
    db.commit()
    known = dict(db.execute(select(m.SourceItem.external_id, m.SourceItem.content_hash).where(
        m.SourceItem.integration_id == integ.id, m.SourceItem.deleted_at.is_(None))).all())
    ctx = SyncContext(cursor=state.cursor, checkpoint=state.checkpoint or {}, known=known)
    n = 0
    try:
        for item in connector.sync(ctx):
            n += 1
            if isinstance(item, Deletion):
                if _delete(db, integ, item.external_id):
                    report.deleted += 1
            else:
                outcome = _upsert(db, integ, item)
                setattr(report, outcome, getattr(report, outcome) + 1)
                SYNC_ITEMS.labels(integ.kind, outcome).inc()
            if n % CHECKPOINT_EVERY == 0:
                db.commit()
        cursor, checkpoint = connector.checkpoint()
        state.cursor = cursor
        if checkpoint:
            state.checkpoint = checkpoint
        state.last_completed_at = utcnow()
        state.items_created += report.created
        state.items_updated += report.updated
        state.items_deleted += report.deleted
        state.items_unchanged += report.unchanged
        state.rate_limit_remaining = connector.rate_limit_remaining
        state.last_error = None
        integ.status, integ.last_sync_at, integ.last_error = "connected", utcnow(), None
        if getattr(connector, "credentials_changed", False) and cred:
            cred.ciphertext = encrypt_json(connector.credentials)
        publish(db, integ.user_id, SYNC_COMPLETED, {"integration_id": integ.id, **report.as_dict()})
        db.add(m.AuditLog(user_id=integ.user_id, actor="system", action="sync_completed", target_type="integration",
                          target_id=integ.id, details=report.as_dict()))
        db.commit()
    except Exception as exc:
        db.rollback()
        integ = db.get(m.Integration, integration_id)
        state = db.scalar(select(m.SyncState).where(m.SyncState.integration_id == integration_id))
        msg = f"{type(exc).__name__}: {str(exc)[:300]}"
        report.errors.append(msg)
        if integ:
            integ.status, integ.last_error = "error", msg
        if state:
            state.error_count += 1
            state.last_error = msg
        db.commit()
        log.error("sync_failed", integration_id=integration_id, error=msg)
        raise
    finally:
        report.seconds = round(time.perf_counter() - t0, 3)
    if dispatch_events:
        dispatch(db, integ.user_id if integ else None)
    return report


def _upsert(db: Session, integ: m.Integration, item: Normalized) -> str:
    h = content_hash(item)
    si = db.scalar(select(m.SourceItem).where(m.SourceItem.user_id == integ.user_id, m.SourceItem.integration_id == integ.id,
                                              m.SourceItem.external_id == item.external_id))
    if si is not None and si.content_hash == h and si.deleted_at is None:
        si.synced_at = utcnow()
        return "unchanged"
    outcome = "updated" if si is not None else "created"
    if si is None:
        si = m.SourceItem(user_id=integ.user_id, integration_id=integ.id, external_id=item.external_id, kind=item.kind,
                          content_hash=h)
        db.add(si)
        db.flush()
    else:
        from app.ingestion.purge import purge_source_item

        purge_source_item(db, si)  # derived data is rebuilt from the new version
        si.content_hash, si.deleted_at = h, None
    si.external_updated_at = item.external_updated_at
    si.synced_at = utcnow()
    si.processing_status = "pending"
    write_content(db, integ, si, item)
    publish(db, integ.user_id, SOURCE_ITEM_UPSERTED, {"source_item_id": si.id, "kind": item.kind})
    return outcome


def write_content(db: Session, integ: m.Integration, si: m.SourceItem, item: Normalized) -> None:
    uid = integ.user_id
    if isinstance(item, NormalizedEmail):
        db.add(m.Email(user_id=uid, source_item_id=si.id, message_id=item.message_id, in_reply_to=item.in_reply_to,
                       references=item.references, from_addr=item.from_addr.lower(), from_name=item.from_name,
                       to_addrs=item.to, cc_addrs=item.cc, subject=item.subject[:500], body=item.body, sent_at=item.sent_at,
                       attachments=item.attachments, labels=item.labels))
    elif isinstance(item, NormalizedEvent):
        db.add(m.CalendarEvent(user_id=uid, source_item_id=si.id, title=item.title[:500], description=item.description,
                               location=item.location, start_at=item.start_at, end_at=item.end_at, attendees=item.attendees,
                               organizer=item.organizer, notes=item.notes, status=item.status))
    elif isinstance(item, NormalizedDocument):
        store_document_bytes(db, uid, si, item.filename, item.content, title=item.title, author=item.author,
                             authored_at=item.authored_at, declared_mime=item.mime_type)
    elif isinstance(item, NormalizedNote):
        proj = None
        if item.project:
            proj = db.scalar(select(m.Project).where(m.Project.user_id == uid, m.Project.name == item.project))
        note = m.Note(user_id=uid, source_item_id=si.id, title=item.title[:300], body=item.body, tags=item.tags,
                      project_id=proj.id if proj else None)
        if item.external_updated_at:  # keep the source's own timestamps (file mtime, demo story time)
            note.created_at = note.updated_at = item.external_updated_at
        db.add(note)
    db.flush()


def _delete(db: Session, integ: m.Integration, external_id: str) -> bool:
    si = db.scalar(select(m.SourceItem).where(m.SourceItem.integration_id == integ.id, m.SourceItem.external_id == external_id))
    if si is None or si.deleted_at is not None:
        return False
    si.deleted_at = utcnow()
    publish(db, integ.user_id, SOURCE_ITEM_DELETED, {"source_item_id": si.id})
    return True
