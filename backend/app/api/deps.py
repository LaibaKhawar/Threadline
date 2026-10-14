"""Request dependencies: DB session, authenticated user, CSRF and rate limiting."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Iterator
from datetime import UTC, datetime
from threading import Lock

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import user_id_var
from app.core.security import CSRF_HEADER, SESSION_COOKIE, csrf_valid, hash_token
from app.db import models as m
from app.db.session import SessionLocal
from app.ingestion.workspace import Workspace

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_session(request: Request, db: Session = Depends(get_db)) -> m.Session:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(401, "not authenticated")
    sess = db.scalar(select(m.Session).where(m.Session.token_hash == hash_token(token)))
    if sess is None or sess.expires_at.replace(tzinfo=sess.expires_at.tzinfo or UTC) < datetime.now(UTC):
        raise HTTPException(401, "session expired")
    if request.method not in SAFE_METHODS and not csrf_valid(token, request.headers.get(CSRF_HEADER)):
        raise HTTPException(403, "CSRF token missing or invalid")
    return sess


def current_user(sess: m.Session = Depends(current_session), db: Session = Depends(get_db)) -> m.User:
    user = db.get(m.User, sess.user_id)
    if user is None:
        raise HTTPException(401, "user not found")
    user_id_var.set(user.id)
    return user


def workspace(user: m.User = Depends(current_user), db: Session = Depends(get_db)) -> Workspace:
    return Workspace(db, user.id)


def require_admin(user: m.User = Depends(current_user)) -> m.User:
    if user.role != "admin":
        raise HTTPException(403, "admin only")
    return user


class RateLimiter:
    """Sliding-window limiter per (client, bucket). In-process; use a Redis-backed limiter when running
    several API replicas (documented in docs/security.md)."""

    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str, bucket: str, limit: int, window: float = 60.0) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[(key, bucket)]
            while q and q[0] <= now - window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def rate_limit(bucket: str, limit: int | None = None, *, auth: bool = False):  # type: ignore[no-untyped-def]
    def dep(request: Request) -> None:
        s = get_settings()
        lim = limit or (s.auth_rate_limit_per_minute if auth else s.rate_limit_per_minute)
        if not limiter.check(client_key(request), bucket, lim):
            raise HTTPException(429, "too many requests")

    return dep
