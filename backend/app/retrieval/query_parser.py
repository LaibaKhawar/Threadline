"""Parse a natural-language query into filters: people, projects, orgs, source types, time range, intents.

"What did Ahmed promise about the migration during our September meetings?"
  -> people=[Ahmed Khan], types={commitment, event}, time=2026-09-01..2026-09-30, intents={promises},
     keywords="migration"
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m
from app.extraction.temporal import extract_temporal
from app.extraction.text import STOPWORDS, normalize_name
from app.resolution.entity_resolution import org_key

TYPE_WORDS = {
    "email": ["email", "emails", "mail", "message", "messages", "thread", "threads", "inbox", "wrote", "sent me", "replied"],
    "event": ["meeting", "meetings", "call", "calls", "sync", "calendar", "1:1", "standup", "review meeting"],
    "document": ["document", "documents", "doc", "docs", "file", "files", "pdf", "deck", "spreadsheet", "proposal doc", "architecture document"],
    "note": ["note", "notes"],
    "commitment": ["promise", "promised", "promises", "commitment", "commitments", "committed", "waiting on", "owe", "owes", "agreed to"],
    "decision": ["decide", "decided", "decision", "decisions", "chose", "choose", "chosen", "pick", "picked", "settled on", "go with",
                 "went with", "superseded"],
    "task": ["task", "tasks", "todo", "to-do", "blocked"],
}
INTENTS = {
    "waiting_on": [r"waiting (?:on|for)", r"what (?:do|does) .+ owe me", r"haven'?t (?:replied|responded|sent)"],
    "my_promises": [r"\bwhat (?:promises|commitments) did i\b", r"\bi promised\b", r"\bmy (?:promises|commitments)\b", r"\bdid i (?:promise|commit)\b"],
    "blocked": [r"\bblocked\b", r"\bblockers?\b"],
    "superseded": [r"\bsuperseded\b", r"\b(?:changed|reversed|replaced) decisions?\b", r"decisions? (?:changed|have changed)"],
    "changed": [r"\bwhat changed\b", r"\bchanges?\b", r"\bmoved\b", r"\bbefore it was moved\b", r"\bhistory\b"],
    "latest": [r"\blatest\b", r"\bmost recent\b", r"\bnewest\b", r"\blast\b(?! (?:month|week|year))"],
    "unanswered": [r"haven'?t replied", r"not replied", r"no reply", r"unanswered", r"awaiting (?:a )?(?:reply|response)"],
    "attention": [r"need(?:s)? (?:my )?attention", r"at risk", r"requir(?:e|ing) attention"],
    "prepare": [r"\bprepare\b", r"\bprep\b", r"\bbrief\b", r"\bbefore (?:the|my|tomorrow'?s|today'?s) .*meeting"],
    "everything": [r"\beverything\b", r"\ball (?:about|related)\b"],
    "when": [r"^\s*when\b", r"\bwhat date\b"],
    "employment": [r"\bwork(?:ed|s)? (?:for|at)\b", r"\bwhich company\b", r"\bemployer\b"],
    "deadline": [r"\bdeadline\b", r"\bdue\b", r"\blaunch date\b"],
}


@dataclass
class ParsedQuery:
    raw: str
    keywords: str
    person_ids: list[str] = field(default_factory=list)
    person_names: list[str] = field(default_factory=list)
    project_ids: list[str] = field(default_factory=list)
    project_names: list[str] = field(default_factory=list)
    org_ids: list[str] = field(default_factory=list)
    types: set[str] = field(default_factory=set)
    time_start: datetime | None = None
    time_end: datetime | None = None
    time_text: str | None = None
    intents: set[str] = field(default_factory=set)

    def as_dict(self) -> dict[str, object]:
        return {
            "keywords": self.keywords, "people": self.person_names, "projects": self.project_names,
            "types": sorted(self.types), "intents": sorted(self.intents), "time_text": self.time_text,
            "time_start": self.time_start.isoformat() if self.time_start else None,
            "time_end": self.time_end.isoformat() if self.time_end else None,
        }


def parse_query(db: Session, user_id: str, query: str, *, now: datetime, tz: str = "UTC",
                self_person_id: str | None = None) -> ParsedQuery:
    q = query.strip()
    low = q.lower()
    pq = ParsedQuery(raw=q, keywords=q)
    consumed: list[str] = []
    # people: aliases (full names first), then unique first names
    aliases = list(db.execute(select(m.PersonAlias.alias, m.PersonAlias.alias_norm, m.PersonAlias.person_id).where(
        m.PersonAlias.user_id == user_id, m.PersonAlias.kind == "name")).all())
    people = {p.id: p for p in db.scalars(select(m.Person).where(m.Person.user_id == user_id, m.Person.merged_into_id.is_(None)))}
    for _alias, norm, pid in sorted(aliases, key=lambda a: -len(a[1])):
        if len(norm) < 3 or pid not in people:
            continue
        if re.search(r"\b" + re.escape(norm) + r"(?:'s)?\b", low):
            if pid not in pq.person_ids and pid != self_person_id:
                pq.person_ids.append(pid)
                pq.person_names.append(people[pid].display_name)
                consumed.append(norm)
    # "me"/"I" as the self person only matters for intents; not added as a filter
    for pr in db.scalars(select(m.Project).where(m.Project.user_id == user_id)):
        names = [pr.name.lower(), *[k.lower() for k in (pr.keywords or []) if len(k) >= 5 and False]]
        for n in names:
            if re.search(r"\b" + re.escape(n) + r"\b", low):
                pq.project_ids.append(pr.id)
                pq.project_names.append(pr.name)
                consumed.append(n)
                break
    for o in db.scalars(select(m.Organization).where(m.Organization.user_id == user_id)):
        if re.search(r"\b" + re.escape(o.name.lower()) + r"\b", low) or (len(org_key(o.name)) >= 4 and re.search(r"\b" + re.escape(org_key(o.name)) + r"\b", low)):
            pq.org_ids.append(o.id)
            consumed.append(o.name.lower())
    for t, words in TYPE_WORDS.items():
        if any(re.search(r"\b" + re.escape(w) + r"\b", low) for w in words):
            pq.types.add(t)
    for intent, pats in INTENTS.items():
        if any(re.search(p, low) for p in pats):
            pq.intents.add(intent)
    # temporal scope (resolved relative to the workspace clock)
    past = bool(re.search(r"\b(did|was|were|had|worked|sent|decided|happened|changed|promised|agreed|said|met|"
                          r"discussed|wrote|replied|before|last|ago|earlier)\b", low))
    for tm in extract_temporal(q, now, tz, prefer="past" if past else "nearest"):
        if tm.text.lower() in ("may",):
            continue
        pq.time_start, pq.time_end, pq.time_text = tm.range_start, tm.range_end, tm.text
        consumed.append(tm.text.lower())
        if tm.granularity == "day" and tm.relation == "on":
            # "before tomorrow's meeting" style day references widen to that day
            pass
        break
    # keywords: drop names, type words, intent filler and stopwords
    kw = low
    for c in consumed:
        kw = re.sub(r"\b" + re.escape(c) + r"(?:'s)?\b", " ", kw)
    kw = re.sub(r"\b(project|what|which|who|did|does|do|show|find|tell|me|my|our|about|regarding|related|to|with|the|during|"
                r"everything|all|any|are|is|was|were|i|we|you|on|in|for|of|am|have|has|had|been|from|that|this|"
                r"promise[sd]?|waiting|meetings?|emails?|documents?|decisions?|tasks?|notes?|latest|most|recent|"
                r"when|did|need|needs|attention|before|it|moved|changed|month|week|last|this)\b", " ", kw)
    words = [w for w in re.findall(r"[a-z0-9][a-z0-9\-\.]+", kw) if w not in STOPWORDS]
    pq.keywords = " ".join(words)
    return pq


def name_tokens(name: str) -> list[str]:
    return normalize_name(name).split()
