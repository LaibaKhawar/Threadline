"""Celery application. Queues: events (domain events), sync, default (jobs, proactive, evaluation)."""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings

s = get_settings()
celery_app = Celery("threadline", broker=s.redis_url, backend=s.redis_url, include=["app.workers.tasks"])
celery_app.conf.update(
    task_acks_late=True,  # redeliver if a worker dies mid-task (handlers are idempotent)
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_default_queue="default",
    task_routes={"app.workers.tasks.process_event_task": {"queue": "events"}, "app.workers.tasks.run_job_task": {"queue": "default"}},
    beat_schedule={
        "proactive-intelligence": {"task": "app.workers.tasks.proactive_tick", "schedule": 15 * 60},
        "memory-consolidation": {"task": "app.workers.tasks.consolidation_tick", "schedule": 24 * 3600},
        "requeue-stuck-events": {"task": "app.workers.tasks.requeue_events", "schedule": 5 * 60},
    },
    timezone="UTC",
)
