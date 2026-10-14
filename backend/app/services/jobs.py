"""Background jobs with status, retries, failure reasons and dead-lettering.

In single-process mode (EVENTS_EAGER=true) jobs run on a background thread inside the API process;
otherwise they are dispatched to Celery. Both paths go through `execute_job`, so behaviour matches.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import JOBS
from app.core.timeutil import utcnow
from app.db import models as m
from app.db.session import SessionLocal

log = get_logger(__name__)


def enqueue(db: Session, *, kind: str, user_id: str | None, payload: dict[str, Any], idempotency_key: str | None = None,
            max_attempts: int = 3) -> m.Job:
    if idempotency_key:
        existing = db.scalar(select(m.Job).where(m.Job.idempotency_key == idempotency_key))
        if existing and existing.status in ("queued", "running"):
            return existing
        if existing:
            existing.idempotency_key = f"{idempotency_key}:{existing.id}"  # free the key for a new run
            db.flush()
    job = m.Job(kind=kind, user_id=user_id, payload=payload, idempotency_key=idempotency_key, max_attempts=max_attempts)
    db.add(job)
    db.commit()
    if get_settings().events_eager:
        threading.Thread(target=execute_job, args=(job.id,), daemon=True).start()
    else:
        from app.workers.tasks import run_job_task

        run_job_task.delay(job.id)
    return job


def execute_job(job_id: str) -> str:
    db = SessionLocal()
    try:
        job = db.get(m.Job, job_id)
        if job is None or job.status in ("succeeded", "dead"):
            return job.status if job else "missing"
        while True:
            job.status, job.attempts, job.started_at = "running", job.attempts + 1, utcnow()
            db.commit()
            try:
                result = _run(db, job)
                job = db.get(m.Job, job_id)
                assert job is not None
                job.status, job.finished_at, job.error = "succeeded", utcnow(), None
                job.progress = {**(job.progress or {}), "result": result, "percent": 100, "message": "done"}
                db.commit()
                JOBS.labels(job.kind, "succeeded").inc()
                return "succeeded"
            except Exception as exc:
                db.rollback()
                job = db.get(m.Job, job_id)
                assert job is not None
                job.error = f"{type(exc).__name__}: {str(exc)[:500]}"
                retryable = getattr(exc, "retryable", True)
                if job.attempts >= job.max_attempts or not retryable:
                    job.status, job.finished_at = "dead", utcnow()
                    db.commit()
                    JOBS.labels(job.kind, "dead").inc()
                    log.error("job_dead", job_id=job.id, kind=job.kind, error=job.error)
                    return "dead"
                job.status = "queued"
                db.commit()
                JOBS.labels(job.kind, "retry").inc()
                time.sleep(min(30, 2 ** job.attempts))  # exponential backoff
    finally:
        db.close()


def _run(db: Session, job: m.Job) -> dict[str, Any]:
    if job.kind == "sync":
        from app.ingestion.sync import run_sync

        def progress(pct: int, msg: str) -> None:
            j = db.get(m.Job, job.id)
            if j:
                j.progress = {"percent": pct, "message": msg}
                db.commit()

        progress(5, "syncing")
        report = run_sync(db, job.payload["integration_id"])
        return report.as_dict()
    if job.kind == "load_demo":
        from app.services.accounts import load_demo_workspace

        user = db.get(m.User, job.user_id)
        assert user is not None
        load_demo_workspace(db, user)
        return {"ok": True}
    if job.kind == "proactive":
        from app.ingestion.workspace import Workspace
        from app.intelligence.proactive import run_proactive

        assert job.user_id
        ws = Workspace(db, job.user_id)
        from app.commitments.resolution import resolve_commitments

        r = resolve_commitments(ws)
        p = run_proactive(ws)
        db.commit()
        return {**r, **p}
    if job.kind == "reprocess":
        from app.domain.events import SOURCE_ITEM_UPSERTED, dispatch, publish

        n = 0
        for si in db.scalars(select(m.SourceItem).where(m.SourceItem.user_id == job.user_id, m.SourceItem.deleted_at.is_(None))):
            publish(db, si.user_id, SOURCE_ITEM_UPSERTED, {"source_item_id": si.id})
            n += 1
        db.commit()
        dispatch(db, job.user_id)
        return {"reprocessed": n}
    if job.kind == "evaluation":
        from evals.run_all import run_suites

        return run_suites(job.payload.get("suites"), use_llm=job.payload.get("use_llm", False))
    raise ValueError(f"unknown job kind {job.kind}")
