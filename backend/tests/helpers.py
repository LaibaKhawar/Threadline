"""Helpers to put content into the system through the real sync path (normalised items -> events)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.connectors.base import NormalizedDocument, NormalizedEmail, NormalizedEvent
from app.db import models as m
from app.domain.events import dispatch
from app.ingestion.sync import _upsert


def dt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


def integration(db: Session, user_id: str, kind: str = "demo") -> m.Integration:
    i = m.Integration(user_id=user_id, kind=kind, name=f"test-{kind}", config={})
    db.add(i)
    db.flush()
    return i


def ingest(db: Session, integ: m.Integration, items: list[Any], *, process: bool = True) -> None:
    for it in items:
        _upsert(db, integ, it)
    db.commit()
    if process:
        dispatch(db, integ.user_id)


_counter = {"n": 0}


def email(frm: tuple[str, str], to: list[tuple[str, str]], subject: str, body: str, at: str, *, reply_to: str | None = None,
          attachments: list[str] | None = None, key: str | None = None) -> NormalizedEmail:
    _counter["n"] += 1
    k = key or f"e{_counter['n']}"
    return NormalizedEmail(external_id=k, message_id=f"<{k}@test>", subject=subject, body=body, from_addr=frm[1], from_name=frm[0],
                           to=[{"name": n, "email": e} for n, e in to], cc=[], sent_at=dt(at),
                           in_reply_to=f"<{reply_to}@test>" if reply_to else None, references=[f"<{reply_to}@test>"] if reply_to else [],
                           attachments=[{"filename": a} for a in (attachments or [])])


def meeting(key: str, title: str, start: str, end: str, attendees: list[tuple[str, str]], notes: str | None = None,
            description: str | None = None) -> NormalizedEvent:
    return NormalizedEvent(external_id=key, title=title, start_at=dt(start), end_at=dt(end),
                           attendees=[{"name": n, "email": e} for n, e in attendees], notes=notes, description=description)


def document(key: str, filename: str, content: bytes, author: str | None = None, at: str | None = None) -> NormalizedDocument:
    return NormalizedDocument(external_id=key, filename=filename, content=content, author=author, authored_at=dt(at) if at else None)


ALEX = ("Alex Morgan", "alex@example.com")
SARAH = ("Sarah Chen", "sarah@acme.com")
AHMED = ("Ahmed Khan", "ahmed@lumen.io")
LAIBA = ("Laiba Hassan", "laiba@lumen.io")
DANIEL = ("Daniel Smith", "daniel@lumen.io")
