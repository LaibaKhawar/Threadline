"""Deterministic temporal expression extraction and normalisation.

Resolves expressions such as "by Friday", "next week", "end of the month", "Oct 3rd",
"in two weeks", "September" against a reference timestamp (usually the source's sent time),
so "Friday" in an email sent on Tuesday 2026-09-15 means 2026-09-18.

Every mention keeps its character span so extracted deadlines stay traceable to source text.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_WD_ABBR = {"mon": 0, "tue": 1, "tues": 1, "wed": 2, "thu": 3, "thur": 3, "thurs": 3, "fri": 4, "sat": 5, "sun": 6}
MONTHS = {
    m.lower(): i
    for i, m in enumerate(calendar.month_name)
    if m
} | {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m} | {"sept": 9}
_NUM_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
              "eight": 8, "nine": 9, "ten": 10, "couple of": 2, "few": 3}

_WD = r"(?P<wd>monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tues?|wed|thur?s?|fri|sat|sun)\b"
_MON = r"(?P<mon>january|february|march|april|may|june|july|august|september|sept|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\b\.?"
_NUM = r"(?P<n>\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|couple of|few)"


@dataclass(frozen=True)
class TemporalMention:
    text: str
    start: int
    end: int
    value: datetime  # resolved point (deadline semantics: end of the referenced day/period)
    range_start: datetime
    range_end: datetime
    granularity: str  # day | week | month | year
    relation: str = "on"  # on | by | before | after | ago

    @property
    def date(self) -> date:
        return self.value.date()


def _eod(d: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(d, time(23, 59, 59), tzinfo=tz)


def _sod(d: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(d, time(0, 0, 0), tzinfo=tz)


def _week_bounds(d: date) -> tuple[date, date]:
    start = d - timedelta(days=d.weekday())
    return start, start + timedelta(days=6)


def _month_bounds(y: int, m: int) -> tuple[date, date]:
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def _add_months(y: int, m: int, k: int) -> tuple[int, int]:
    idx = y * 12 + (m - 1) + k
    return idx // 12, idx % 12 + 1


def _num(token: str) -> int:
    token = token.lower()
    return int(token) if token.isdigit() else _NUM_WORDS.get(token, 1)


def _wd_index(tok: str) -> int:
    tok = tok.lower()
    if tok in WEEKDAYS:
        return WEEKDAYS.index(tok)
    return _WD_ABBR[tok.rstrip(".")]


class _Rule:
    def __init__(self, pattern: str, fn):  # type: ignore[no-untyped-def]
        self.re = re.compile(pattern, re.IGNORECASE)
        self.fn = fn


def _rules() -> list[_Rule]:
    rules: list[_Rule] = []

    def add(pattern: str):  # type: ignore[no-untyped-def]
        def deco(fn):  # type: ignore[no-untyped-def]
            rules.append(_Rule(pattern, fn))
            return fn

        return deco

    @add(r"\b(?P<y>20\d\d)-(?P<m>\d{1,2})-(?P<d>\d{1,2})\b")
    def iso(m, ref):  # type: ignore[no-untyped-def]
        d = date(int(m["y"]), int(m["m"]), int(m["d"]))
        return d, d, "day"

    @add(r"\b" + _MON + r"\s+(?P<d>\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(?P<y>20\d\d))?\b")
    def mon_day(m, ref):  # type: ignore[no-untyped-def]
        return _explicit(int(m["d"]), MONTHS[m["mon"].lower().rstrip(".")], m["y"], ref)

    @add(r"\b(?P<d>\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MON + r"(?:,?\s+(?P<y>20\d\d))?")
    def day_mon(m, ref):  # type: ignore[no-untyped-def]
        return _explicit(int(m["d"]), MONTHS[m["mon"].lower().rstrip(".")], m["y"], ref)

    @add(r"\bday after tomorrow\b")
    def dat(m, ref):  # type: ignore[no-untyped-def]
        d = ref.date() + timedelta(days=2)
        return d, d, "day"

    @add(r"\b(?P<w>today|tonight|eod|end of (?:the )?day|this evening|this afternoon|this morning)\b")
    def today(m, ref):  # type: ignore[no-untyped-def]
        return ref.date(), ref.date(), "day"

    @add(r"\btomorrow\b")
    def tomorrow(m, ref):  # type: ignore[no-untyped-def]
        d = ref.date() + timedelta(days=1)
        return d, d, "day"

    @add(r"\byesterday\b")
    def yesterday(m, ref):  # type: ignore[no-untyped-def]
        d = ref.date() - timedelta(days=1)
        return d, d, "day"

    @add(r"\b(?:eow|end of (?P<nx>next )?(?:the )?week)\b")
    def end_of_week(m, ref):  # type: ignore[no-untyped-def]
        base = ref.date() + timedelta(days=7 if m["nx"] else 0)
        friday = _week_bounds(base)[0] + timedelta(days=4)
        return friday, friday, "day"

    @add(r"\b(?:eom|end of (?P<nx>next )?(?:the )?month)\b")
    def end_of_month(m, ref):  # type: ignore[no-untyped-def]
        y, mo = _add_months(ref.year, ref.month, 1 if m["nx"] else 0)
        end = _month_bounds(y, mo)[1]
        return end, end, "day"

    @add(r"\bend of " + _MON)
    def end_of_named_month(m, ref):  # type: ignore[no-untyped-def]
        mo = MONTHS[m["mon"].lower().rstrip(".")]
        y = ref.year if mo >= ref.month - 6 else ref.year + 1
        end = _month_bounds(y, mo)[1]
        return end, end, "day"

    @add(r"\b(?P<mod>next|this|last|coming)\s+" + _WD)
    def mod_weekday(m, ref):  # type: ignore[no-untyped-def]
        target = _wd_index(m["wd"])
        today = ref.date()
        mod = m["mod"].lower()
        if mod == "last":
            delta = (today.weekday() - target) % 7 or 7
            d = today - timedelta(days=delta)
        elif mod in ("this", "coming"):
            d = today + timedelta(days=(target - today.weekday()) % 7)
        else:  # next: the occurrence in the following calendar week
            week_start = _week_bounds(today)[0] + timedelta(days=7)
            d = week_start + timedelta(days=target)
        return d, d, "day"

    @add(r"\b(?:on\s+|by\s+|until\s+|before\s+)?" + _WD)
    def weekday(m, ref):  # type: ignore[no-untyped-def]
        target = _wd_index(m["wd"])
        today = ref.date()
        d = today + timedelta(days=(target - today.weekday()) % 7)
        return d, d, "day"

    @add(r"\b(?P<mod>next|this|last)\s+(?P<unit>week|month|year|quarter)\b")
    def mod_period(m, ref):  # type: ignore[no-untyped-def]
        mod, unit = m["mod"].lower(), m["unit"].lower()
        k = {"next": 1, "this": 0, "last": -1}[mod]
        if unit == "week":
            s, e = _week_bounds(ref.date() + timedelta(days=7 * k))
            return s, e, "week"
        if unit == "month":
            y, mo = _add_months(ref.year, ref.month, k)
            s, e = _month_bounds(y, mo)
            return s, e, "month"
        if unit == "quarter":
            q = (ref.month - 1) // 3 + k
            y = ref.year + q // 4
            q %= 4
            s = date(y, q * 3 + 1, 1)
            e = _month_bounds(y, q * 3 + 3)[1]
            return s, e, "month"
        y = ref.year + k
        return date(y, 1, 1), date(y, 12, 31), "year"

    @add(r"\b(?:in|within)\s+(?:the\s+next\s+)?" + _NUM + r"\s+(?P<unit>days?|weeks?|months?)\b")
    def in_n(m, ref):  # type: ignore[no-untyped-def]
        n, unit = _num(m["n"]), m["unit"].lower()
        if unit.startswith("day"):
            d = ref.date() + timedelta(days=n)
        elif unit.startswith("week"):
            d = ref.date() + timedelta(days=7 * n)
        else:
            y, mo = _add_months(ref.year, ref.month, n)
            d = date(y, mo, min(ref.day, calendar.monthrange(y, mo)[1]))
        return d, d, "day"

    @add(_NUM + r"\s+(?P<unit>days?|weeks?|months?)\s+ago\b")
    def ago(m, ref):  # type: ignore[no-untyped-def]
        n, unit = _num(m["n"]), m["unit"].lower()
        days = n if unit.startswith("day") else 7 * n if unit.startswith("week") else 30 * n
        d = ref.date() - timedelta(days=days)
        return d, d, "day"

    @add(r"\b(?:in\s+|during\s+|since\s+|mid-?)?" + _MON + r"(?:\s+(?P<y>20\d\d))?")
    def month_only(m, ref):  # type: ignore[no-untyped-def]
        mo = MONTHS[m["mon"].lower().rstrip(".")]
        if m["y"]:
            y = int(m["y"])
        else:
            pref = _PREFER.get()
            cands = [ref.year - 1, ref.year, ref.year + 1]
            if pref == "past":
                y = max(c for c in cands if date(c, mo, 1) <= ref.date())
            elif pref == "future":
                y = min(c for c in cands if _month_bounds(c, mo)[1] >= ref.date())
            else:
                y = min(cands, key=lambda c: abs((date(c, mo, 15) - ref.date()).days))
        s, e = _month_bounds(y, mo)
        if m.group(0).lower().startswith("mid"):
            mid = date(y, mo, 15)
            return mid, mid, "day"
        return s, e, "month"

    return rules


def _explicit(day: int, month: int, year: str | None, ref: datetime):  # type: ignore[no-untyped-def]
    y = int(year) if year else ref.year
    try:
        d = date(y, month, day)
    except ValueError:
        return None
    if not year and (ref.date() - d).days > 180:
        d = date(y + 1, month, day)  # "Jan 5" written in December means next January
    return d, d, "day"


from contextvars import ContextVar  # noqa: E402

_PREFER: ContextVar[str] = ContextVar("temporal_prefer", default="future")
_RULES = _rules()
_RELATION = re.compile(r"\b(by|before|until|no later than|after|since|on)\s*$", re.IGNORECASE)
# Words that look like month names but are usually not ("may" as a modal verb, "march" as a verb).
_AMBIGUOUS = {"may", "march", "sun", "sat", "wed", "mar", "jan"}


def extract_temporal(text: str, reference: datetime, tz: str = "UTC", prefer: str = "future") -> list[TemporalMention]:
    """Return non-overlapping temporal mentions resolved against ``reference``.

    ``prefer`` resolves bare month names: "future" for messages ("we'll ship in March" written in
    October means next March), "past" for questions about history ("what did Sarah do in March?")."""
    token = _PREFER.set(prefer)
    try:
        return _extract(text, reference, tz)
    finally:
        _PREFER.reset(token)


def _extract(text: str, reference: datetime, tz: str) -> list[TemporalMention]:
    zone = ZoneInfo(tz)
    ref = reference.astimezone(zone) if reference.tzinfo else reference.replace(tzinfo=zone)
    taken: list[tuple[int, int]] = []
    out: list[TemporalMention] = []
    for rule in _RULES:
        for m in rule.re.finditer(text):
            s, e = m.span()
            if any(not (e <= a or s >= b) for a, b in taken):
                continue
            token = m.group(0).strip().lower().rstrip(".")
            bare = token.split()[-1] if token.split() else token
            if bare in _AMBIGUOUS and not _ambiguous_ok(text, s, e, m.group(0)):
                continue
            try:
                res = rule.fn(m, ref)
            except (ValueError, KeyError):
                continue
            if not res:
                continue
            d0, d1, gran = res
            before = text[max(0, s - 20) : s]
            rel_m = _RELATION.search(before)
            rel = (rel_m.group(1).lower() if rel_m else "on").replace("no later than", "by")
            if m.group(0).lower().startswith(("by ", "before ", "until ")):
                rel = m.group(0).split()[0].lower()
            if rel == "until":
                rel = "by"
            taken.append((s, e))
            out.append(
                TemporalMention(
                    text=m.group(0).strip().rstrip("."),
                    start=s,
                    end=e,
                    value=_eod(d1, zone),
                    range_start=_sod(d0, zone),
                    range_end=_eod(d1, zone),
                    granularity=gran,
                    relation=rel if rel in ("by", "before", "after", "since", "on") else "on",
                )
            )
    out.sort(key=lambda t: t.start)
    # "Wednesday 12 November": the explicit date wins over the bare weekday next to it.
    merged: list[TemporalMention] = []
    for i, t in enumerate(out):
        nxt = out[i + 1] if i + 1 < len(out) else None
        is_wd = re.fullmatch(r"(?:on |by |until |before )?" + _WD.replace("(?P<wd>", "(?:"), t.text, re.I)
        if is_wd and nxt and 0 <= nxt.start - t.end <= 3 and nxt.granularity == "day":
            continue
        merged.append(t)
    return merged


def _ambiguous_ok(text: str, s: int, e: int, matched: str) -> bool:
    """'May'/'March' only count as months when capitalised and next to a day number or 'in'."""
    word = matched.strip().split()[-1]
    if matched.strip().lower().startswith(("in ", "during ", "since ", "mid")) and word[:1].isupper():
        return True
    if not word[:1].isupper():
        return False
    window = text[max(0, s - 6) : min(len(text), e + 6)].lower()
    return bool(re.search(r"\d", text[e : e + 5])) or bool(re.search(r"\b(in|during|since|until|of)\s*$", text[max(0, s - 10) : s].lower())) or "mid" in window


def first_deadline(text: str, reference: datetime, tz: str = "UTC") -> TemporalMention | None:
    """The first future-or-today day-precision mention, used as a commitment deadline."""
    for m in extract_temporal(text, reference, tz):
        if m.relation in ("after", "since"):
            continue
        if m.range_end.date() >= reference.astimezone(ZoneInfo(tz)).date():
            return m
    return None
