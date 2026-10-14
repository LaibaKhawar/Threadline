"""Rule-based named-entity extraction for people, organisations and projects.

It combines a gazetteer of already-known entities (contacts, aliases, projects) with contextual
patterns (greetings, reporting verbs, signatures, corporate suffixes). Known entities are matched
with high precision; unseen names need a contextual cue before they are accepted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.extraction.schemas import OrgMention, PersonMention, ProjectMention, Span
from app.extraction.temporal import MONTHS, WEEKDAYS

FREEMAIL = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com", "proton.me", "protonmail.com"}
_ORG_SUFFIX = r"(?:Inc|Ltd|LLC|Corp|Corporation|Labs|Group|Technologies|Systems|Partners|GmbH|Analytics|Capital|Health|Bank|Security|Solutions|Software|Consulting|Ventures|Media|Studio|Studios|Insurance|Logistics)"
_NAME = r"[A-Z][a-z]+(?:[-'][A-Z][a-z]+)?"
_CUE_AFTER = (
    r"(?:said|says|will|would|'ll|’ll|mentioned|asked|promised|agreed|confirmed|suggested|wrote|"
    r"is going to|has|had|wants|needs|thinks|noted|replied|sent|shared|owns|leads|is)"
)
_NON_NAMES = (
    {w.capitalize() for w in WEEKDAYS}
    | {m.capitalize() for m in MONTHS}
    | set(
        ["I", "We", "You", "They", "He", "She", "It", "The", "This", "That", "These", "Those", "Thanks", "Thank", "Hi", "Hello", "Hey", "Dear", "Best", "Regards", "Cheers", "Re", "Fwd", "Fw", "Please", "Let", "Also", "Just", "So", "And", "But", "Or", "If", "When", "Once", "After", "Before", "Today", "Tomorrow", "Yesterday", "Monday", "Project", "Team", "All", "Everyone", "Agenda", "Notes", "Action", "Items", "Attached", "Here", "There", "Sounds", "Great", "Good", "Quick", "Update", "Sure", "Yes", "No", "Ok", "Okay", "Happy", "Looking", "Following", "Kind", "Sincerely", "Note", "Decision", "Summary", "Next", "Last", "Q1", "Q2", "Q3", "Q4", "Our", "Your", "My", "Their", "His", "Her", "Its", "Any", "Some", "Each", "Both", "Why", "What", "Who", "How", "Where", "Which", "Can", "Could", "Would", "Should", "Will", "Shall", "May", "Might", "Must", "Do", "Does", "Did", "Is", "Are", "Was", "Were", "Be", "Been", "Have", "Has", "Had", "Not", "Only", "Still", "Then", "Now", "Is", "Morning", "Afternoon", "Evening", "Welcome", "Congrats", "Sorry", "Apologies", "FYI", "PS", "Draft", "Final", "Status", "Open", "Closed"]
    )
)


@dataclass
class Gazetteer:
    """Known entity surface forms for this user, built from the database."""

    people: dict[str, str] = field(default_factory=dict)  # normalised alias -> canonical display name
    person_emails: dict[str, str] = field(default_factory=dict)  # email -> display name
    orgs: dict[str, str] = field(default_factory=dict)  # lower name -> canonical
    org_domains: dict[str, str] = field(default_factory=dict)  # domain -> canonical
    projects: dict[str, str] = field(default_factory=dict)  # lower name/keyword -> project name

    def add_person(self, display: str, aliases: list[str] | None = None, emails: list[str] | None = None) -> None:
        for a in [display, *(aliases or [])]:
            if a and "@" not in a:
                self.people[a.lower()] = display
        for e in emails or []:
            self.person_emails[e.lower()] = display

    def first_name_index(self) -> dict[str, list[str]]:
        idx: dict[str, list[str]] = {}
        for display in set(self.people.values()):
            first = display.split()[0].lower()
            idx.setdefault(first, [])
            if display not in idx[first]:
                idx[first].append(display)
        return idx


def org_from_domain(domain: str) -> str | None:
    domain = domain.lower().strip()
    if not domain or domain in FREEMAIL:
        return None
    root = domain.split(".")[-2] if domain.count(".") >= 1 else domain
    if root in ("co", "com") and domain.count(".") >= 2:
        root = domain.split(".")[-3]
    return root.replace("-", " ").title()


def extract_people(text: str, gaz: Gazetteer) -> list[PersonMention]:
    found: dict[tuple[int, int], PersonMention] = {}

    def put(name: str, s: int, e: int, conf: float, role: str = "mentioned") -> None:
        if any(not (e <= a or s >= b) for a, b in found):
            return
        found[(s, e)] = PersonMention(name=name, span=Span(start=s, end=e, text=text[s:e]), role=role, confidence=conf)  # type: ignore[arg-type]

    # 1) gazetteer: full names/aliases first (longest first), then unique first names.
    for alias in sorted(gaz.people, key=len, reverse=True):
        if len(alias) < 3:
            continue
        for m in re.finditer(r"(?<![\w@.])" + re.escape(alias) + r"(?![\w@])", text, flags=re.IGNORECASE):
            if not m.group(0)[0].isupper():
                continue
            put(gaz.people[alias], m.start(), m.end(), 0.95)
    for first, displays in gaz.first_name_index().items():
        if len(displays) != 1:
            continue
        for m in re.finditer(r"\b" + re.escape(first.capitalize()) + r"\b", text):
            put(displays[0], m.start(), m.end(), 0.85)

    # 2) greetings: "Hi Laiba," / "Dear Ms Chen"
    for m in re.finditer(r"(?:^|\n)\s*(?:Hi|Hello|Hey|Dear)\s+(" + _NAME + r"(?:\s+" + _NAME + r")?)\s*[,!\n]", text):
        name = m.group(1)
        if name.split()[0] not in _NON_NAMES:
            put(_canonical(name, gaz), m.start(1), m.end(1), 0.85, "addressee")

    # 3) unseen names next to reporting verbs / prepositions: "Priya said", "with Tomás Vega"
    for m in re.finditer(r"\b(" + _NAME + r"(?:\s+" + _NAME + r")?)\s+" + _CUE_AFTER + r"\b", text):
        name = m.group(1)
        if name.split()[0] in _NON_NAMES or name in _NON_NAMES:
            continue
        if _is_org_or_project(name, gaz):
            continue
        put(_canonical(name, gaz), m.start(1), m.end(1), 0.7)
    for m in re.finditer(r"\b(?:with|from|to|cc|ask|asked|thank|thanks|ping|told|loop in|looping in)\s+(" + _NAME + r"\s+" + _NAME + r")\b", text):
        name = m.group(1)
        if name.split()[0] in _NON_NAMES or _is_org_or_project(name, gaz) or name.split()[1] in _NON_NAMES:
            continue
        put(_canonical(name, gaz), m.start(1), m.end(1), 0.65)
    return sorted(found.values(), key=lambda p: p.span.start if p.span else 0)


def _canonical(name: str, gaz: Gazetteer) -> str:
    return gaz.people.get(name.lower(), name)


def _is_org_or_project(name: str, gaz: Gazetteer) -> bool:
    low = name.lower()
    return low in gaz.orgs or low in gaz.projects or low.startswith("project ")


def extract_orgs(text: str, gaz: Gazetteer) -> list[OrgMention]:
    found: dict[str, OrgMention] = {}
    for name_l, canonical in sorted(gaz.orgs.items(), key=lambda kv: -len(kv[0])):
        m = re.search(r"\b" + re.escape(name_l) + r"\b", text, flags=re.IGNORECASE)
        if m and m.group(0)[0].isupper():
            found.setdefault(canonical.lower(), OrgMention(name=canonical, span=Span(start=m.start(), end=m.end(), text=m.group(0)), confidence=0.9))
    for m in re.finditer(r"\b((?:[A-Z][A-Za-z0-9&]+\s){0,2}[A-Z][A-Za-z0-9&]+)\s+" + _ORG_SUFFIX + r"\b\.?", text):
        name = m.group(0).rstrip(".")
        while name.split()[0] in _NON_NAMES | {"At", "From", "With", "For", "In"} and len(name.split()) > 2:
            name = name.split(" ", 1)[1]
        if name.split()[0] in _NON_NAMES:
            continue
        found.setdefault(name.lower(), OrgMention(name=name, span=Span(start=m.start(), end=m.end(), text=m.group(0)), confidence=0.75))
    for m in re.finditer(r"\b(?:joined|join|at|from|with|for)\s+([A-Z][A-Za-z0-9]+(?:\s[A-Z][A-Za-z0-9]+)?)\s+(?:as|in|on|team|since)\b", text):
        cand = m.group(1)
        if cand.split()[0] in _NON_NAMES or cand.lower() in gaz.people or cand.lower() in gaz.projects:
            continue
        if cand.split()[0].lower() in gaz.first_name_index():
            continue
        found.setdefault(cand.lower(), OrgMention(name=cand, span=Span(start=m.start(1), end=m.end(1), text=cand), confidence=0.55))
    return list(found.values())


def extract_projects(text: str, gaz: Gazetteer) -> list[ProjectMention]:
    found: dict[str, ProjectMention] = {}
    for m in re.finditer(r"\bProject\s+([A-Z][a-zA-Z0-9]+)\b", text):
        name = gaz.projects.get(m.group(1).lower(), m.group(1))
        found.setdefault(name.lower(), ProjectMention(name=name, span=Span(start=m.start(), end=m.end(), text=m.group(0)), confidence=0.9))
    for key, name in gaz.projects.items():
        if len(key) < 3:
            continue
        hit = re.search(r"\b" + re.escape(key) + r"\b", text, flags=re.IGNORECASE)
        if hit:
            conf = 0.85 if hit.group(0)[0].isupper() else 0.6
            found.setdefault(name.lower(), ProjectMention(name=name, span=Span(start=hit.start(), end=hit.end(), text=hit.group(0)), confidence=conf))
    return list(found.values())
