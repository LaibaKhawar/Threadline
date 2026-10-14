"""Memory service: semantic facts with supersession, episodic events, procedural preferences.

Lifecycle: ingestion -> extraction -> consolidation -> retrieval -> update -> supersession -> archival.
A changed fact never deletes the old one: the old row becomes `superseded` with valid_to set, the
new row links back, and both stay queryable ("what was the deadline before it moved?").
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m
from app.extraction.text import normalize_name, stable_hash


class MemoryService:
    def __init__(self, db: Session, user_id: str) -> None:
        self.db = db
        self.user_id = user_id

    def record_fact(
        self,
        *,
        subject: tuple[str, str],
        attribute: str,
        value: str,
        content: str,
        valid_from: datetime | None,
        observed_at: datetime,
        source: tuple[str, str] | None,
        span: str | None,
        confidence: float = 0.8,
        origin: str = "extraction",
    ) -> m.Memory:
        """Upsert a semantic fact; same value reinforces, different value supersedes (in time order)."""
        key = stable_hash(self.user_id, "fact", subject, attribute, normalize_name(value), source[1] if source else "")
        existing = self.db.scalar(select(m.Memory).where(m.Memory.user_id == self.user_id, m.Memory.dedupe_key == key))
        if existing:
            return existing
        same_attr = list(self.db.scalars(select(m.Memory).where(
            m.Memory.user_id == self.user_id, m.Memory.kind == "semantic", m.Memory.subject_type == subject[0],
            m.Memory.subject_id == subject[1], m.Memory.attribute == attribute, m.Memory.status != "archived")))
        for o in same_attr:
            if normalize_name(o.value or "") == normalize_name(value) and o.status == "active":
                o.reinforcement_count += 1
                o.confidence = min(0.99, max(o.confidence, confidence) + 0.02)
                start = valid_from or observed_at
                if o.valid_from and start and start < o.valid_from:  # an earlier statement of the same fact dates it
                    o.valid_from, o.observed_at = start, observed_at
                    o.source_type, o.source_id = (source[0], source[1]) if source else (o.source_type, o.source_id)
                    o.evidence_span = span or o.evidence_span
                    self._reorder(subject, attribute)
                return o
        mem = m.Memory(user_id=self.user_id, kind="semantic", content=content, subject_type=subject[0],
                       subject_id=subject[1], attribute=attribute, value=value, confidence=confidence,
                       valid_from=valid_from or observed_at, observed_at=observed_at,
                       source_type=source[0] if source else None, source_id=source[1] if source else None,
                       evidence_span=span, dedupe_key=key, origin=origin)
        self.db.add(mem)
        self.db.flush()
        self._reorder(subject, attribute)
        return mem

    def _reorder(self, subject: tuple[str, str], attribute: str) -> None:
        rows = sorted(self.db.scalars(select(m.Memory).where(
            m.Memory.user_id == self.user_id, m.Memory.kind == "semantic", m.Memory.subject_type == subject[0],
            m.Memory.subject_id == subject[1], m.Memory.attribute == attribute, m.Memory.status != "archived")),
            key=lambda r: (r.valid_from or r.observed_at or datetime.min, r.created_at or datetime.min))
        # User-entered facts outrank extracted ones observed earlier.
        for i, r in enumerate(rows):
            later = rows[i + 1] if i + 1 < len(rows) else None
            if later is not None:
                r.status, r.superseded_by_id, r.valid_to = "superseded", later.id, later.valid_from
            else:
                r.status, r.superseded_by_id, r.valid_to = "active", None, None

    def history(self, subject: tuple[str, str], attribute: str | None = None) -> list[m.Memory]:
        q = select(m.Memory).where(m.Memory.user_id == self.user_id, m.Memory.subject_type == subject[0],
                                   m.Memory.subject_id == subject[1])
        if attribute:
            q = q.where(m.Memory.attribute == attribute)
        return list(self.db.scalars(q.order_by(m.Memory.valid_from)))

    def value_at(self, subject: tuple[str, str], attribute: str, at: datetime) -> m.Memory | None:
        for r in reversed(self.history(subject, attribute)):
            if (r.valid_from is None or r.valid_from <= at) and (r.valid_to is None or r.valid_to > at):
                return r
        return None

    def record_episode(self, *, content: str, occurred_at: datetime, subject: tuple[str, str] | None,
                       source: tuple[str, str] | None, span: str | None = None, confidence: float = 1.0) -> m.Memory:
        key = stable_hash(self.user_id, "episode", source, content[:200])
        existing = self.db.scalar(select(m.Memory).where(m.Memory.user_id == self.user_id, m.Memory.dedupe_key == key))
        if existing:
            return existing
        mem = m.Memory(user_id=self.user_id, kind="episodic", content=content, subject_type=subject[0] if subject else None,
                       subject_id=subject[1] if subject else None, valid_from=occurred_at, observed_at=occurred_at,
                       source_type=source[0] if source else None, source_id=source[1] if source else None,
                       evidence_span=span, confidence=confidence, dedupe_key=key)
        self.db.add(mem)
        return mem

    def add_procedural(self, content: str) -> m.Memory:
        key = stable_hash(self.user_id, "procedural", normalize_name(content))
        existing = self.db.scalar(select(m.Memory).where(m.Memory.user_id == self.user_id, m.Memory.dedupe_key == key))
        if existing:
            existing.status = "active"
            return existing
        mem = m.Memory(user_id=self.user_id, kind="procedural", content=content.strip(), confidence=1.0,
                       dedupe_key=key, origin="user", observed_at=datetime.now().astimezone())
        self.db.add(mem)
        return mem

    def procedural(self) -> list[str]:
        return [r.content for r in self.db.scalars(select(m.Memory).where(
            m.Memory.user_id == self.user_id, m.Memory.kind == "procedural", m.Memory.status == "active"))]

    def consolidate(self, now: datetime, *, archive_after_days: int = 120) -> dict[str, int]:
        """Merge duplicate facts, archive stale low-value episodes. Nothing is hard-deleted."""
        stats = {"merged": 0, "archived": 0}
        seen: dict[tuple, m.Memory] = {}
        for r in self.db.scalars(select(m.Memory).where(m.Memory.user_id == self.user_id, m.Memory.kind == "semantic",
                                                        m.Memory.status == "active").order_by(m.Memory.created_at)):
            k = (r.subject_type, r.subject_id, r.attribute, normalize_name(r.value or ""))
            if k in seen:
                keep = seen[k]
                keep.reinforcement_count += r.reinforcement_count
                keep.confidence = min(0.99, max(keep.confidence, r.confidence))
                r.status, r.superseded_by_id = "archived", keep.id
                stats["merged"] += 1
            else:
                seen[k] = r
        cutoff = now - timedelta(days=archive_after_days)
        for r in self.db.scalars(select(m.Memory).where(m.Memory.user_id == self.user_id, m.Memory.kind == "episodic",
                                                        m.Memory.status == "active", m.Memory.valid_from < cutoff)):
            if r.confidence < 0.9:
                r.status = "archived"
                stats["archived"] += 1
        return stats
