"""Per-user processing context: settings, clock, gazetteer, resolver, graph and memory services."""

from __future__ import annotations

from datetime import datetime
from functools import cached_property

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutil import ensure_aware, utcnow
from app.db import models as m
from app.extraction.entities import Gazetteer
from app.memory.graph import GraphService
from app.memory.memories import MemoryService
from app.resolution.entity_resolution import EntityResolver


class Workspace:
    def __init__(self, db: Session, user_id: str) -> None:
        self.db = db
        self.user_id = user_id
        s = db.get(m.UserSettings, user_id)
        if s is None:
            s = m.UserSettings(user_id=user_id)
            db.add(s)
            db.flush()
        self.settings = s

    @property
    def tz(self) -> str:
        return self.settings.timezone or "UTC"

    def now(self) -> datetime:
        """Demo workspaces pin the clock so overdue/follow-up logic is reproducible."""
        return ensure_aware(self.settings.clock_override) or utcnow()

    @property
    def self_person_id(self) -> str | None:
        return self.settings.self_person_id

    @property
    def self_emails(self) -> set[str]:
        return {e.lower() for e in (self.settings.self_emails or [])}

    @cached_property
    def resolver(self) -> EntityResolver:
        return EntityResolver(self.db, self.user_id)

    @cached_property
    def graph(self) -> GraphService:
        return GraphService(self.db, self.user_id)

    @cached_property
    def memory(self) -> MemoryService:
        return MemoryService(self.db, self.user_id)

    def gazetteer(self) -> Gazetteer:
        g = Gazetteer()
        people = {p.id: p for p in self.db.scalars(select(m.Person).where(
            m.Person.user_id == self.user_id, m.Person.merged_into_id.is_(None)))}
        aliases: dict[str, list[str]] = {}
        emails: dict[str, list[str]] = {}
        for a in self.db.scalars(select(m.PersonAlias).where(m.PersonAlias.user_id == self.user_id)):
            (emails if a.kind == "email" else aliases).setdefault(a.person_id, []).append(a.alias)
        for pid, p in people.items():
            g.add_person(p.display_name, aliases.get(pid, []), emails.get(pid, []))
        for o in self.db.scalars(select(m.Organization).where(m.Organization.user_id == self.user_id)):
            g.orgs[o.name.lower()] = o.name
            if o.domain:
                g.org_domains[o.domain] = o.name
        for pr in self.db.scalars(select(m.Project).where(m.Project.user_id == self.user_id)):
            g.projects[pr.name.lower()] = pr.name
            for k in pr.keywords or []:
                if len(k) >= 4:
                    g.projects[k.lower()] = pr.name
        return g

    def ensure_self_person(self, display_name: str, emails: list[str]) -> m.Person:
        if self.settings.self_person_id:
            p = self.db.get(m.Person, self.settings.self_person_id)
            if p:
                return p
        res = self.resolver.resolve_person(display_name, emails[0] if emails else None)
        p = self.db.get(m.Person, res.person_id)
        assert p is not None
        p.is_self = True
        for e in emails[1:]:
            self.resolver.resolve_person(display_name, e)
        self.settings.self_person_id = p.id
        self.settings.self_emails = [e.lower() for e in emails]
        return p
