from __future__ import annotations

from sqlalchemy import select

from app.db import models as m
from app.db.session import SessionLocal
from app.workers.celery_app import celery_app


@celery_app.task(bind=True, max_retries=5, default_retry_delay=5)
def process_event_task(self, event_id: str) -> str:  # type: ignore[no-untyped-def]
    from app.domain.events import dispatch, process_event

    db = SessionLocal()
    try:
        status = process_event(db, event_id)
        ev = db.get(m.DomainEvent, event_id)
        if status == "failed":
            ev = db.get(m.DomainEvent, event_id)
            if ev is not None:
                ev.status = "queued"  # owned by this retry; dispatch() will not enqueue it again
                db.commit()
            raise self.retry(countdown=min(300, 5 * 2 ** self.request.retries))
        if ev is not None:
            dispatch(db, ev.user_id)  # enqueue events produced by the handlers
        return status
    finally:
        db.close()


@celery_app.task
def run_job_task(job_id: str) -> str:
    from app.services.jobs import execute_job

    return execute_job(job_id)


@celery_app.task
def proactive_tick() -> int:
    from app.commitments.resolution import resolve_commitments
    from app.ingestion.workspace import Workspace
    from app.intelligence.proactive import run_proactive

    db = SessionLocal()
    n = 0
    try:
        for uid in db.scalars(select(m.User.id)):
            ws = Workspace(db, uid)
            resolve_commitments(ws)
            run_proactive(ws)
            db.commit()
            n += 1
    finally:
        db.close()
    return n


@celery_app.task
def consolidation_tick() -> int:
    from app.ingestion.workspace import Workspace

    db = SessionLocal()
    try:
        for uid in db.scalars(select(m.User.id)):
            ws = Workspace(db, uid)
            ws.memory.consolidate(ws.now())
            db.commit()
        return 1
    finally:
        db.close()


@celery_app.task
def requeue_events() -> int:
    """Recover events stuck in 'queued'/'processing' (e.g. broker restart)."""
    from datetime import UTC, datetime, timedelta

    db = SessionLocal()
    try:
        cutoff = datetime.now(UTC) - timedelta(minutes=10)
        # "processing" for >10 min since it was *claimed* means its worker died; "queued" that long means the broker lost it.
        stuck = list(db.scalars(select(m.DomainEvent).where(
            ((m.DomainEvent.status == "processing") & (m.DomainEvent.started_at < cutoff))
            | ((m.DomainEvent.status == "queued") & (m.DomainEvent.created_at < cutoff)))))
        for ev in stuck:
            ev.status = "pending"
        db.commit()
        for ev in stuck:
            process_event_task.delay(ev.id)
        return len(stuck)
    finally:
        db.close()
