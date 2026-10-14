"""Entity resolution for people and organisations.

Scoring evidence (each contributes to a match score in [0, 1]):
  * exact email alias                         -> 1.00 (identity)
  * exact full-name alias, unique             -> 0.95
  * full name equal, different email domain   -> 0.75 (could be a personal address; ask the user)
  * first name only, unique among known people-> 0.85, boosted when the person is in this conversation
  * email local part ~ known name at same org -> 0.90
  * Jaro-Winkler name similarity >= 0.92      -> 0.65 (typos / diacritics; ask the user)

Decisions:  score >= AUTO_MERGE -> link to the existing person
            SUGGEST <= score < AUTO_MERGE -> create a new person and queue a MergeCandidate
            otherwise -> create a new person
User merges/splits are permanent: a rejected pair is never proposed again, and aliases moved by a
split resolve to the new person from then on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz.distance import JaroWinkler
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import models as m
from app.extraction.entities import org_from_domain
from app.extraction.text import normalize_name

AUTO_MERGE = 0.9
SUGGEST = 0.6
# Linking a *mention* ("Daniel said…") to a known person is lower-stakes than merging two identities,
# so it uses a lower bar. It never creates or merges people.
LINK = 0.8
_ORG_SUFFIX = re.compile(r"\b(inc|ltd|llc|corp|corporation|co|gmbh|plc|limited|group)\.?$", re.I)


def normalize_org(name: str) -> str:
    n = name.strip().lower()
    n = _ORG_SUFFIX.sub("", n).strip(" ,.")
    return re.sub(r"\s+", " ", n)


def org_key(name: str) -> str:
    """Compact comparison key: 'Lumen Labs' == 'lumenlabs', 'Acme Corp' == 'acmecorp' == 'Acme'."""
    k = re.sub(r"[^a-z0-9]", "", normalize_org(name))
    for suf in ("corp", "inc", "llc", "ltd", "gmbh", "plc"):
        if k.endswith(suf) and len(k) > len(suf) + 2:
            k = k[: -len(suf)]
    return k


@dataclass
class ResolutionResult:
    person_id: str | None
    score: float
    created: bool = False
    reasons: list[str] = field(default_factory=list)
    ambiguous_ids: list[str] = field(default_factory=list)


class EntityResolver:
    def __init__(self, db: Session, user_id: str) -> None:
        self.db = db
        self.user_id = user_id
        self._people: dict[str, m.Person] = {}
        self._aliases: list[m.PersonAlias] = []
        self._orgs: dict[str, m.Organization] = {}
        self._rejected_pairs: set[frozenset[str]] = set()
        self.reload()

    def reload(self) -> None:
        self._people = {p.id: p for p in self.db.scalars(
            select(m.Person).where(m.Person.user_id == self.user_id, m.Person.merged_into_id.is_(None)))}
        self._aliases = list(self.db.scalars(select(m.PersonAlias).where(m.PersonAlias.user_id == self.user_id)))
        self._orgs = {normalize_org(o.name): o for o in self.db.scalars(
            select(m.Organization).where(m.Organization.user_id == self.user_id))}
        self._rejected_pairs = {
            frozenset((c.person_a_id, c.person_b_id))
            for c in self.db.scalars(select(m.MergeCandidate).where(
                m.MergeCandidate.user_id == self.user_id, m.MergeCandidate.status == "rejected"))
        }

    # ------------------------------------------------------------------------------ organisations
    def resolve_org(self, name: str | None = None, domain: str | None = None, *, create: bool = True) -> m.Organization | None:
        if domain:
            domain = domain.lower()
            for o in self._orgs.values():
                if o.domain and o.domain == domain:
                    if name and o.name == org_from_domain(domain) and " " in name:
                        o.name = name
                    return o
            if not name:
                name = org_from_domain(domain)
        if not name:
            return None
        key = normalize_org(name)
        ck = org_key(name)
        for k, o in self._orgs.items():
            ok = org_key(o.name)
            if k == key or ok == ck or (min(len(ok), len(ck)) >= 5 and (ok.startswith(ck) or ck.startswith(ok))):
                if domain and not o.domain:
                    o.domain = domain
                # a name inferred from a domain ("Lumenlabs") gives way to a real one ("Lumen Labs")
                if o.domain and o.name == org_from_domain(o.domain) and name and name != o.name and " " in name:
                    o.name = name
                return o
        for k, o in self._orgs.items():
            if k and (k.split()[0] == key.split()[0]) and JaroWinkler.similarity(k, key) >= 0.9:
                return o
        if not create:
            return None
        name = re.sub(r"^(?:at|from|with|for|in|the)\s+", "", name.strip(), flags=re.I).strip(" ,.")
        if not name:
            return None
        org = m.Organization(user_id=self.user_id, name=name, domain=domain)
        self.db.add(org)
        self.db.flush()
        self._orgs[key] = org
        return org

    # ------------------------------------------------------------------------------------- people
    def _alias_hits(self, value: str, kind: str) -> set[str]:
        norm = value.lower().strip() if kind == "email" else normalize_name(value)
        hits = set()
        for a in self._aliases:
            if a.kind == kind and a.alias_norm == norm:
                pid = self._canonical_id(a.person_id)
                if pid:
                    hits.add(pid)
        return hits

    def _canonical_id(self, pid: str) -> str | None:
        seen = set()
        while pid and pid not in self._people and pid not in seen:
            seen.add(pid)
            p = self.db.get(m.Person, pid)
            if p is None or p.merged_into_id is None:
                return pid if p else None
            pid = p.merged_into_id
        return pid

    def score_candidates(self, name: str | None, email: str | None, context_ids: set[str]) -> list[tuple[str, float, list[str]]]:
        scores: dict[str, tuple[float, list[str]]] = {}

        def bump(pid: str, s: float, reason: str) -> None:
            cur = scores.get(pid, (0.0, []))
            scores[pid] = (max(cur[0], s), [*cur[1], reason])

        domain = email.split("@")[1].lower() if email and "@" in email else None
        if email:
            for pid in self._alias_hits(email, "email"):
                bump(pid, 1.0, "exact email match")
        if name:
            norm = normalize_name(name)
            full_hits = self._alias_hits(name, "name")
            for pid in full_hits:
                p = self._people[pid]
                if len(norm.split()) >= 2:
                    pdomain = p.primary_email.split("@")[1].lower() if p.primary_email and "@" in p.primary_email else None
                    if email and pdomain and domain and pdomain != domain and not self._alias_hits(email, "email"):
                        bump(pid, 0.75, f"same full name, different email domain ({domain} vs {pdomain})")
                    else:
                        bump(pid, 0.95 if len(full_hits) == 1 else 0.7, "exact full-name alias")
                else:
                    in_ctx = [h for h in full_hits if h in context_ids]
                    if len(full_hits) == 1:
                        base = 0.85 + (0.1 if pid in context_ids else 0.0)
                    elif len(in_ctx) == 1 and pid == in_ctx[0]:
                        base = 0.9  # several people share the name, but only one is in this conversation
                    else:
                        base = 0.5
                    bump(pid, base, "matching first-name alias" + (" (in this conversation)" if pid in context_ids else ""))
            if len(norm.split()) == 1 and not full_hits:
                firsts = [pid for pid, p in self._people.items() if normalize_name(p.display_name).split()[:1] == [norm]]
                if len(firsts) == 1:
                    s = 0.85 + (0.1 if firsts[0] in context_ids else 0.0)
                    bump(firsts[0], s, "unique first-name match")
                elif len(firsts) > 1:
                    in_ctx = [f for f in firsts if f in context_ids]
                    if len(in_ctx) == 1:
                        bump(in_ctx[0], 0.9, "first name matches the one participant with that name")
                    else:
                        for f in firsts:
                            bump(f, 0.4, "first name shared by several people")
            if len(norm.split()) >= 2 and not full_hits:
                for pid, p in self._people.items():
                    pn = normalize_name(p.display_name)
                    if len(pn.split()) >= 2:
                        sim = JaroWinkler.similarity(pn, norm)
                        if sim >= 0.92:
                            bump(pid, 0.65, f"similar name ({sim:.2f})")
        if email and not name:
            local = re.split(r"[._\-+]", email.split("@")[0].lower())
            for pid, p in self._people.items():
                parts = normalize_name(p.display_name).split()
                if not parts:
                    continue
                pdomain = p.primary_email.split("@")[1].lower() if p.primary_email and "@" in p.primary_email else None
                if local[0] == parts[0] and (len(local) == 1 or (len(parts) > 1 and local[-1] in (parts[-1], parts[-1][:1]))):
                    s = 0.9 if pdomain == domain else 0.6
                    bump(pid, s, "email local part matches name" + (" at same domain" if pdomain == domain else ""))
        return sorted(((pid, s, r) for pid, (s, r) in scores.items()), key=lambda x: -x[1])

    def resolve_person(
        self,
        name: str | None,
        email: str | None = None,
        *,
        context_ids: set[str] | None = None,
        create: bool = True,
        source: tuple[str, str] | None = None,
        org_hint: str | None = None,
    ) -> ResolutionResult:
        name = (name or "").strip().strip('"') or None
        email = (email or "").strip().lower() or None
        if name and "@" in name and not email:
            email, name = name.lower(), None
        if not name and not email:
            return ResolutionResult(None, 0.0)
        cands = self.score_candidates(name, email, context_ids or set())
        top = cands[0] if cands else None
        if top and top[1] >= AUTO_MERGE:
            pid = top[0]
            self._add_aliases(pid, name, email, source)
            return ResolutionResult(pid, top[1], reasons=top[2])
        if not create:
            if top and top[1] >= LINK and not (len(cands) > 1 and cands[1][1] >= top[1] - 0.05):
                return ResolutionResult(top[0], top[1], reasons=top[2])
            return ResolutionResult(None, top[1] if top else 0.0, reasons=top[2] if top else [],
                                    ambiguous_ids=[c[0] for c in cands if c[1] >= 0.4])
        # A bare first name that is shared by several people is ambiguous: do not create a new person.
        if name and not email and len(name.split()) == 1 and any(c[1] >= 0.4 for c in cands):
            return ResolutionResult(None, top[1] if top else 0.0, reasons=["ambiguous first name"],
                                    ambiguous_ids=[c[0] for c in cands if c[1] >= 0.4])
        person = self._create(name, email, source, org_hint)
        for pid, score, reasons in cands:
            if score >= SUGGEST and frozenset((pid, person.id)) not in self._rejected_pairs:
                self.db.add(m.MergeCandidate(user_id=self.user_id, person_a_id=pid, person_b_id=person.id,
                                             score=round(score, 3), reasons=reasons))
        return ResolutionResult(person.id, 1.0, created=True, reasons=["new person"])

    def _create(self, name: str | None, email: str | None, source: tuple[str, str] | None, org_hint: str | None) -> m.Person:
        display = name or _name_from_email(email or "")
        org = None
        if email and "@" in email:
            org = self.resolve_org(org_hint, email.split("@")[1]) if org_from_domain(email.split("@")[1]) else None
        elif org_hint:
            org = self.resolve_org(org_hint)
        p = m.Person(user_id=self.user_id, display_name=display, primary_email=email,
                     organization_id=org.id if org else None)
        self.db.add(p)
        self.db.flush()
        self._people[p.id] = p
        self._add_aliases(p.id, name or display, email, source)
        return p

    def _add_aliases(self, pid: str, name: str | None, email: str | None, source: tuple[str, str] | None) -> None:
        existing = {(a.alias_norm, a.kind) for a in self._aliases if a.person_id == pid}
        new: list[tuple[str, str, str]] = []
        if name:
            new.append((name, normalize_name(name), "name"))
            first = normalize_name(name).split()[0] if normalize_name(name) else None
            if first and len(normalize_name(name).split()) > 1:
                new.append((name.split()[0], first, "name"))
        if email:
            new.append((email, email.lower(), "email"))
            p = self._people.get(pid)
            if p and not p.primary_email:
                p.primary_email = email
        for alias, norm, kind in new:
            if (norm, kind) in existing or not norm:
                continue
            a = m.PersonAlias(user_id=self.user_id, person_id=pid, alias=alias, alias_norm=norm, kind=kind,
                              source_type=source[0] if source else None, source_id=source[1] if source else None)
            self.db.add(a)
            self._aliases.append(a)
            existing.add((norm, kind))

    # ------------------------------------------------------------------------------ merge / split
    def merge(self, keep_id: str, merge_id: str) -> m.Person:
        keep, gone = self.db.get(m.Person, keep_id), self.db.get(m.Person, merge_id)
        if not keep or not gone or keep.user_id != self.user_id or gone.user_id != self.user_id or keep_id == merge_id:
            raise ValueError("invalid merge")
        for a in self.db.scalars(select(m.PersonAlias).where(m.PersonAlias.person_id == merge_id)):
            dup = self.db.scalar(select(m.PersonAlias).where(
                m.PersonAlias.person_id == keep_id, m.PersonAlias.alias_norm == a.alias_norm, m.PersonAlias.kind == a.kind))
            if dup:
                self.db.delete(a)
            else:
                a.person_id = keep_id
        _repoint_person(self.db, self.user_id, merge_id, keep_id)
        gone.merged_into_id = keep_id
        keep.primary_email = keep.primary_email or gone.primary_email
        keep.organization_id = keep.organization_id or gone.organization_id
        for c in self.db.scalars(select(m.MergeCandidate).where(
                m.MergeCandidate.user_id == self.user_id,
                or_(m.MergeCandidate.person_a_id.in_([keep_id, merge_id]), m.MergeCandidate.person_b_id.in_([keep_id, merge_id])))):
            if {c.person_a_id, c.person_b_id} == {keep_id, merge_id}:
                c.status = "merged"
        self.db.flush()
        self.reload()
        return keep

    def split(self, person_id: str, alias_ids: list[str], new_name: str | None = None) -> m.Person:
        src = self.db.get(m.Person, person_id)
        if not src or src.user_id != self.user_id:
            raise ValueError("invalid split")
        aliases = [a for a in self.db.scalars(select(m.PersonAlias).where(m.PersonAlias.id.in_(alias_ids)))
                   if a.person_id == person_id]
        if not aliases:
            raise ValueError("no aliases to split")
        email = next((a.alias for a in aliases if a.kind == "email"), None)
        name = new_name or next((a.alias for a in aliases if a.kind == "name"), None) or _name_from_email(email or "")
        new = m.Person(user_id=self.user_id, display_name=name, primary_email=email, created_by="user")
        self.db.add(new)
        self.db.flush()
        for a in aliases:
            a.person_id = new.id
        if src.primary_email and email and src.primary_email.lower() == email.lower():
            src.primary_email = next((a.alias for a in self.db.scalars(select(m.PersonAlias).where(
                m.PersonAlias.person_id == person_id, m.PersonAlias.kind == "email"))), None)
        # Emails sent from any moved address now belong to the new person.
        for addr in [a.alias_norm for a in aliases if a.kind == "email"]:
            for e in self.db.scalars(select(m.Email).where(m.Email.user_id == self.user_id, m.Email.from_addr == addr)):
                e.sender_person_id = new.id
                for r in self.db.scalars(select(m.Relationship).where(
                        m.Relationship.user_id == self.user_id, m.Relationship.rel_type == "SENT",
                        m.Relationship.src_id == person_id, m.Relationship.dst_id == e.id)):
                    r.src_id = new.id
        self.db.add(m.MergeCandidate(user_id=self.user_id, person_a_id=person_id, person_b_id=new.id, score=0.0,
                                     reasons=["split by user"], status="rejected"))
        self.db.flush()
        self.reload()
        return new


def _name_from_email(email: str) -> str:
    local = email.split("@")[0] if email else "Unknown"
    parts = [p for p in re.split(r"[._\-+]", local) if p and not p.isdigit()]
    return " ".join(p.capitalize() for p in parts) or local


def _repoint_person(db: Session, user_id: str, old: str, new: str) -> None:
    for model, cols in (
        (m.Email, ["sender_person_id"]),
        (m.Task, ["owner_person_id", "blocked_by_person_id"]),
        (m.Commitment, ["actor_person_id", "recipient_person_id"]),
        (m.Document, ["author_person_id"]),
    ):
        for col in cols:
            for row in db.scalars(select(model).where(model.user_id == user_id, getattr(model, col) == old)):
                setattr(row, col, new)
    for rel in db.scalars(select(m.Relationship).where(m.Relationship.user_id == user_id, m.Relationship.src_type == "person", m.Relationship.src_id == old)):
        rel.src_id = new
    for rel in db.scalars(select(m.Relationship).where(m.Relationship.user_id == user_id, m.Relationship.dst_type == "person", m.Relationship.dst_id == old)):
        rel.dst_id = new
    for ep in db.scalars(select(m.EventParticipant).where(m.EventParticipant.person_id == old)):
        if db.get(m.EventParticipant, (ep.event_id, new)):
            db.delete(ep)
        else:
            ep.person_id = new
    for pm in db.scalars(select(m.ProjectMember).where(m.ProjectMember.person_id == old)):
        if db.get(m.ProjectMember, (pm.project_id, new)):
            db.delete(pm)
        else:
            pm.person_id = new
    db.flush()
