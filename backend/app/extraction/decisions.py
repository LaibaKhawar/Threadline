"""Decision detection plus temporal facts (deadline moves, employment changes, blockers)."""

from __future__ import annotations

import re
from datetime import datetime

from app.extraction.schemas import BlockerFact, DeadlineChange, DecisionExtraction, EmploymentFact
from app.extraction.temporal import extract_temporal
from app.extraction.text import split_sentences

_CHOICE = r"(?P<chosen>[A-Za-z0-9][\w .+#/\-']{0,60}?)"
_REJ = r"(?:\s*,?\s+(?:rather than|instead of|over|and not|not|vs\.?|versus)\s+(?P<rejected>[\w .+#/\-']{1,60}?))?"
_END = r"\s*(?:for\s+(?P<for>[\w \-]{2,40}?))?\s*(?=[.,;:!?)]|\s+(?:for|because|since|as|going forward|from now on|after|given|so|which)\b|$)"
_DECISION_PATTERNS = [
    re.compile(
        r"\b(?:we|the team|I|leadership|everyone)\s*(?:'ve|’ve|\s+have|\s+has)?\s+(?:finally\s+)?(?:decided|agreed|chosen|chose|settled|"
        r"aligned|concluded)\s+(?:to\s+(?:use|go with|adopt|move to|switch to|stick with|keep|standardi[sz]e on|build on|"
        r"go back to|revert to|move back to)|on|that we(?:'ll| will) (?:use|go with))\s+" + _CHOICE + _REJ + _END,
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:we(?:'re|’re| are)|we(?:'ll|’ll| will))\s+(?:going with|go with|moving to|switching to|standardi[sz]ing on|"
        r"reverting to|moving back to|going back to)\s+" + _CHOICE + _REJ + _END,
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:decision|final decision|resolution)\s*(?:is|was|:)\s*(?:to\s+(?:use|go with)\s+)?" + _CHOICE + _REJ + _END, re.IGNORECASE),
    re.compile(
        r"\bswitch(?:ing|ed)?\s+from\s+(?P<rejected>[\w .+#/\-']{1,40}?)\s+to\s+" + _CHOICE + _END, re.IGNORECASE
    ),
    re.compile(
        r"\b(?:we|the team|I)\s*(?:'ve|’ve|\s+have)?\s+(?:decided|agreed)\s+to\s+(?:run|host|deploy|build|launch|keep)\s+"
        r"(?:the\s+)?[\w ]{0,40}?\s+(?:on|with|in|using)\s+" + _CHOICE
        + r"(?:\s*,?\s+(?:rather than|instead of|over|and not|not)\s+(?P<rejected>[\w .+#/\-']{1,60}?))" + _END,
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:approved|signed off on|greenlit|green-lit)\s+(?:the\s+)?" + _CHOICE + _END, re.IGNORECASE),
]
_REVERSAL = re.compile(r"\b(revert|reverting|moving back|going back|reversed|reverse|overturn|change of plan|no longer going with)\b", re.I)

TOPIC_LEXICON: dict[str, list[str]] = {
    "database": ["postgres", "postgresql", "mongodb", "mongo", "mysql", "dynamodb", "cassandra", "sqlite", "cockroach", "database"],
    "frontend framework": ["react", "vue", "angular", "svelte", "next.js", "nextjs", "remix"],
    "cloud provider": ["aws", "gcp", "google cloud", "azure", "digitalocean", "hetzner"],
    "message queue": ["kafka", "rabbitmq", "sqs", "pubsub", "nats", "redis streams"],
    "payments vendor": ["stripe", "paddle", "adyen", "braintree"],
    "pricing": ["pricing", "per seat", "per-seat", "usage-based", "flat fee", "tier", "price", "$"],
    "launch date": ["launch", "go-live", "release date", "ship date"],
    "vendor": ["vendor", "supplier", "agency", "contractor"],
    "auth provider": ["auth0", "okta", "cognito", "clerk", "keycloak"],
    "analytics": ["mixpanel", "amplitude", "segment", "posthog"],
    "llm provider": ["openai", "anthropic", "ollama", "llama", "mistral", "gpt", "claude"],
    "hiring": ["hire", "candidate", "offer"],
}


def infer_topic(text: str, chosen: str, rejected: list[str], for_phrase: str | None = None) -> str:
    hay = " ".join([chosen, *rejected]).lower()
    for topic, words in TOPIC_LEXICON.items():
        if any(w in hay for w in words):
            return topic
    if for_phrase:
        return re.sub(r"^(?:the|our|a)\s+", "", for_phrase.strip().lower())
    low = text.lower()
    for topic, words in TOPIC_LEXICON.items():
        if any(re.search(r"\b" + re.escape(w) + r"\b", low) for w in words if w != "$"):
            return topic
    return re.sub(r"^(?:the|a|an|our)\s+", "", chosen.lower()).split(" for ")[0][:60]


def _clean(v: str | None) -> str | None:
    if not v:
        return None
    v = re.sub(r"^(?:the|a|an|our|using)\s+", "", v.strip(), flags=re.I).strip(" .'\"")
    return v or None


def extract_decisions(text: str) -> list[DecisionExtraction]:
    out: list[DecisionExtraction] = []
    for sent in split_sentences(text):
        s = sent.text
        if re.search(r"\b(should we|do we|whether to|haven't decided|not decided|undecided|still deciding|"
                     r"proposal is to|propose|suggest|considering|thinking about|might|maybe)\b", s, re.I):
            continue
        for pat in _DECISION_PATTERNS:
            m = pat.search(s)
            if not m:
                continue
            chosen = _clean(m.group("chosen"))
            if not chosen or len(chosen) < 2 or chosen.lower() in ("it", "this", "that", "them", "to", "a"):
                continue
            rejected = [r for r in [_clean(m.groupdict().get("rejected"))] if r]
            for_phrase = m.groupdict().get("for")
            topic = infer_topic(s, chosen, rejected, for_phrase)
            conf = 0.85 if pat is _DECISION_PATTERNS[0] else 0.75
            out.append(
                DecisionExtraction(
                    topic=topic,
                    chosen=chosen,
                    rejected=rejected,
                    reverses_previous=bool(_REVERSAL.search(s)),
                    source_span=s,
                    span_start=sent.start,
                    span_end=sent.end,
                    confidence=conf,
                )
            )
            break
    return out


_DEADLINE_SUBJECT = (
    r"(?P<subject>(?:the\s+)?(?:[\w\-]+\s){0,3}?(?:deadline|launch|due date|delivery|release|go-live|cutover|"
    r"migration|demo|review|kickoff|handoff|submission|beta|rollout|deliverable|proposal|deck|report))"
)
_FOR = r"(?:\s+(?:for|on|of)\s+(?:the\s+)?(?P<for>[\w\- ]{2,40}?))?"
_DEADLINE_MOVE = [
    re.compile(_DEADLINE_SUBJECT + _FOR + r"\s+(?:has\s+been\s+|have\s+been\s+|is\s+being\s+|was\s+|is\s+|got\s+)?(?:now\s+)?"
               r"(?:moved|pushed|changed|shifted|extended|slipped|postponed|rescheduled|brought forward|delayed|bumped)"
               r"(?:\s+(?:back|out|forward))?\s+(?:to|until|till)\s+(?P<when>[^.,;]+)", re.I),
    re.compile(r"\b(?:push(?:ing)?|mov(?:e|ing)|shift(?:ing)?|delay(?:ing)?|bump(?:ing)?)\s+" + _DEADLINE_SUBJECT +
               r"\s+(?:back\s+|out\s+)?(?:to|until)\s+(?P<when>[^.,;]+)", re.I),
    re.compile(_DEADLINE_SUBJECT + r"\s+is\s+now\s+(?:due\s+|on\s+|set for\s+|scheduled for\s+)?(?P<when>[^.,;]+)", re.I),
    re.compile(_DEADLINE_SUBJECT + r"\s+(?:is|are|remains)\s+(?:still\s+)?(?:scheduled|set|planned|targeted|due|booked)\s+(?:for|on|by)\s+(?P<when>[^.,;]+)", re.I),
    re.compile(r"\bnew\s+(?P<subject>deadline|due date|launch date|date)\s*(?:is|:)\s*(?P<when>[^.,;]+)", re.I),
]


def extract_deadline_changes(text: str, sent_at: datetime, tz: str = "UTC") -> list[DeadlineChange]:
    out: list[DeadlineChange] = []
    for sent in split_sentences(text):
        for pat in _DEADLINE_MOVE:
            m = pat.search(sent.text)
            if not m:
                continue
            mentions = extract_temporal(m.group("when"), sent_at, tz)
            if not mentions:
                continue
            t = mentions[0]
            subject = re.sub(r"^the\s+", "", m.group("subject").strip(), flags=re.I)
            if m.groupdict().get("for"):
                subject = f"{subject} for {m.group('for').strip()}"
            kind = "set" if re.search(r"\b(scheduled|set|planned|targeted|booked)\s+(for|on|by)\b|\bis\s+(?:still\s+)?due\b", m.group(0), re.I) else "moved"
            out.append(DeadlineChange(kind=kind, subject=subject, new_due_at=t.value, due_text=t.text, source_span=sent.text,
                                      span_start=sent.start, span_end=sent.end))
            break
    return out


_JOINED = re.compile(
    r"\b(?P<who>I|I've|I have|[A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+(?:has\s+|have\s+|just\s+|recently\s+)*(?:joined|moved to|started at|"
    r"is now at|am now at|'m now at|switched to)\s+(?P<org>[A-Z][\w&]+(?:\s[A-Z][\w&]+)?)(?:\s+as\s+(?:an?\s+)?(?P<title>[\w ]{3,40}?))?(?=[.,;!]|\s+(?:and|last|this|in|from|on)\b|$)"
)
_LEFT = re.compile(r"\b(?P<who>I|I've|I have|[A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+(?:has\s+|have\s+|just\s+)*(?:left|departed|is leaving|am leaving)\s+(?P<org>[A-Z][\w&]+(?:\s[A-Z][\w&]+)?)")
_SIGNATURE_LINE = re.compile(r"^(?P<title>[A-Z][\w &/\-]{2,50}?)\s*(?:,|\||@|·|-|at)\s*(?P<org>[A-Z][\w&]+(?:\s[A-Z][\w&]+)?)\s*$")


def extract_employment(text: str, signature: str, speaker: str | None) -> list[EmploymentFact]:
    out: list[EmploymentFact] = []
    for m in _JOINED.finditer(text):
        who = m.group("who")
        person = speaker if who.startswith("I") else who
        if not person or m.group("org") in ("Project", "The", "Our"):
            continue
        out.append(EmploymentFact(person=person, organization=m.group("org"), title=(m.group("title") or None),
                                  kind="joined", source_span=m.group(0), confidence=0.8))
    for m in _LEFT.finditer(text):
        who = m.group("who")
        person = speaker if who.startswith("I") else who
        if person:
            out.append(EmploymentFact(person=person, organization=m.group("org"), kind="left",
                                      source_span=m.group(0), confidence=0.75))
    if signature and speaker:
        for line in signature.splitlines()[:4]:
            sm = _SIGNATURE_LINE.match(line.strip())
            if sm and len(sm.group("title").split()) <= 6:
                out.append(EmploymentFact(person=speaker, organization=sm.group("org"), title=sm.group("title").strip(),
                                          kind="signature", source_span=line.strip(), confidence=0.7))
                break
    return out


_BLOCKED = re.compile(
    r"\b(?P<item>(?:the\s+)?[\w\- ]{3,50}?)\s+(?:is|are|remains|is still|are still)\s+blocked\s+(?:on|by)\s+"
    r"(?P<who>[A-Z][a-z]+(?:\s[A-Z][a-z]+)?|legal|security|finance|procurement)",
)
_WAITING = re.compile(
    r"\b(?:still\s+)?(?:waiting\s+on|blocked\s+on|blocked\s+by|pending\s+(?:approval\s+from|input\s+from))\s+"
    r"(?P<who>[A-Z][a-z]+(?:\s[A-Z][a-z]+)?)(?:'s)?\s*(?:for\s+(?:the\s+)?(?P<item>[\w\- ]{3,60}))?"
)


def extract_blockers(text: str) -> list[BlockerFact]:
    out: list[BlockerFact] = []
    for sent in split_sentences(text):
        m = _BLOCKED.search(sent.text) or _WAITING.search(sent.text)
        if not m:
            continue
        item = (m.groupdict().get("item") or "").strip() or sent.text[:80]
        item = re.sub(r"^(?:the|we're|we are|i'm|i am)\s+", "", item, flags=re.I)
        out.append(BlockerFact(blocked_item=item, blocked_by=m.group("who"), source_span=sent.text,
                               span_start=sent.start, span_end=sent.end))
    return out
