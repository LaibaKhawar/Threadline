"""Domain events + transactional outbox.

Producers call `publish()` inside their DB transaction. After commit, `dispatch()` hands pending
events to Celery (or processes them inline when EVENTS_EAGER=true). Handlers are idempotent and
keyed by event id, so redelivery after a crash is safe.

    SourceItemUpserted -> process_content  (normalise, extract, resolve, graph, embed, associate)
    ContentProcessed   -> resolve_commitments (fulfilment / cancellation / overdue)
    SyncCompleted      -> proactive_analysis (follow-ups, health, notifications) + consolidation
    SourceItemDeleted  -> purge_derived
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import EVENTS
from app.core.timeutil import utcnow
from app.db.models import DomainEvent

log = get_logger(__name__)

SOURCE_ITEM_UPSERTED = "SourceItemUpserted"
SOURCE_ITEM_DELETED = "SourceItemDeleted"
CONTENT_PROCESSED = "ContentProcessed"
SYNC_COMPLETED = "SyncCompleted"
USER_CORRECTION = "UserCorrection"

Handler = Callable[[Session, DomainEvent], None]
_HANDLERS: dict[str, list[Handler]] = {}
MAX_ATTEMPTS = 3


def handles(event_type: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        _HANDLERS.setdefault(event_type, []).append(fn)
        return fn

    return deco


def publish(db: Session, user_id: str, type_: str, payload: dict[str, Any]) -> DomainEvent:
    ev = DomainEvent(user_id=user_id, type=type_, payload=payload)
    db.add(ev)
    return ev


def process_event(db: Session, event_id: str) -> str:
    """Run all handlers for one event. Returns final status. Safe to call twice."""
    from sqlalchemy import update

    from app.ingestion import handlers  # noqa: F401  (registers handlers)

    # Atomic claim: only one worker can move an event into "processing".
    claimed = db.execute(update(DomainEvent).where(DomainEvent.id == event_id, DomainEvent.status.in_(["pending", "failed", "queued"]))
                         .values(status="processing", attempts=DomainEvent.attempts + 1, started_at=utcnow())
                         .returning(DomainEvent.id)).first()
    db.commit()
    ev = db.get(DomainEvent, event_id)
    if ev is None:
        return "missing"
    if claimed is None:
        return ev.status  # done, dead, or being processed by someone else
    try:
        for h in _HANDLERS.get(ev.type, []):
            h(db, ev)
        ev.status, ev.processed_at, ev.error = "done", utcnow(), None
        db.commit()
        EVENTS.labels(ev.type, "done").inc()
    except Exception as exc:
        db.rollback()
        ev = db.get(DomainEvent, event_id)
        assert ev is not None
        ev.error = f"{type(exc).__name__}: {str(exc)[:500]}"
        ev.status = "dead" if ev.attempts >= MAX_ATTEMPTS else "failed"
        db.commit()
        EVENTS.labels(ev.type, ev.status).inc()
        log.error("event_failed", event_id=event_id, type=ev.type, attempts=ev.attempts, error=ev.error)
    return ev.status


@contextmanager
def eager_events() -> Iterator[None]:
    """Process events synchronously inside this block, whatever EVENTS_EAGER says.

    Evaluations and benchmarks must measure a fully processed workspace; with Celery dispatch they would
    read it while workers are still processing (this happened in the Docker deployment)."""
    s = get_settings()
    before = s.events_eager
    s.events_eager = True
    try:
        yield
    finally:
        s.events_eager = before


def dispatch(db: Session, user_id: str | None = None, *, limit: int = 10_000) -> int:
    """Process (eager) or enqueue (Celery) pending events. Events created by handlers are picked up too."""
    eager = get_settings().events_eager
    total = 0
    while total < limit:
        q = select(DomainEvent.id).where(DomainEvent.status.in_(["pending", "failed"]),
                                          DomainEvent.attempts < MAX_ATTEMPTS)
        if user_id:
            q = q.where(DomainEvent.user_id == user_id)
        ids = list(db.scalars(q.order_by(DomainEvent.created_at).limit(200)))
        if not ids:
            break
        if eager:
            for eid in ids:
                process_event(db, eid)
        else:
            from app.workers.tasks import process_event_task

            for eid in ids:
                ev = db.get(DomainEvent, eid)
                if ev:
                    ev.status = "queued"
                db.commit()
                process_event_task.delay(eid)
            return total + len(ids)
        total += len(ids)
    return total
