"""Text normalisation helpers shared by the extractors."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

_QUOTE_HEADER = re.compile(r"^\s*On .{5,200}wrote:\s*$", re.MULTILINE)
_FORWARD_HEADER = re.compile(r"^-{2,}\s*(Original Message|Forwarded message)\s*-{2,}", re.MULTILINE | re.IGNORECASE)
_SIG_DELIM = re.compile(r"^(--\s*|__+|Sent from my \w+)$", re.MULTILINE)
_ABBREV = ("e.g.", "i.e.", "etc.", "vs.", "Mr.", "Ms.", "Mrs.", "Dr.", "approx.", "Inc.", "Ltd.", "No.")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])|\n{2,}|\n(?=\s*[-*•]\s)|\n(?=\s*\d+[.)]\s)")


@dataclass(frozen=True)
class Sentence:
    text: str
    start: int
    end: int


def strip_quoted_reply(body: str) -> str:
    """Remove quoted history from a reply so earlier messages are not re-extracted."""
    cut = len(body)
    for pat in (_QUOTE_HEADER, _FORWARD_HEADER):
        m = pat.search(body)
        if m:
            cut = min(cut, m.start())
    lines = body[:cut].splitlines()
    kept = [ln for ln in lines if not ln.lstrip().startswith(">")]
    return "\n".join(kept).rstrip()


def split_signature(body: str) -> tuple[str, str]:
    m = _SIG_DELIM.search(body)
    if m:
        return body[: m.start()].rstrip(), body[m.end() :].strip()
    # Heuristic: a closing like "Thanks,\nName" followed by short lines is a signature block.
    m2 = re.search(r"\n(?:Thanks|Thank you|Best|Regards|Best regards|Cheers|Kind regards|Sincerely),?\s*\n", body)
    if m2:
        return body[: m2.start()].rstrip(), body[m2.end() :].strip()
    # A bare sign-off name on the last line ("\n\nAhmed") is a signature, not content.
    m3 = re.search(r"\n\s*\n([A-Z][a-z]+(?:\s[A-Z][a-z]+){0,2}(?:\n[^\n]{1,80}){0,2})\s*$", body)
    if m3:
        return body[: m3.start()].rstrip(), m3.group(1).strip()
    return body, ""


def split_sentences(text: str) -> list[Sentence]:
    """Sentence splitter that keeps character offsets (needed for provenance spans)."""
    protected = text
    for ab in _ABBREV:
        protected = protected.replace(ab, ab.replace(".", "․"))
    out: list[Sentence] = []
    pos = 0
    for m in _SENT_SPLIT.finditer(protected):
        seg = text[pos : m.start()]
        if seg.strip():
            lead = len(seg) - len(seg.lstrip())
            out.append(Sentence(seg.strip(), pos + lead, pos + lead + len(seg.strip())))
        pos = m.end()
    seg = text[pos:]
    if seg.strip():
        lead = len(seg) - len(seg.lstrip())
        out.append(Sentence(seg.strip(), pos + lead, pos + lead + len(seg.strip())))
    return out


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s@.\-']", " ", name)).strip().lower()


def normalize_subject(subject: str) -> str:
    s = subject or ""
    while True:
        new = re.sub(r"^\s*(re|fw|fwd|aw)\s*:\s*", "", s, flags=re.IGNORECASE)
        if new == s:
            break
        s = new
    return s.strip()


def stable_hash(*parts: object) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p).encode())
        h.update(b"\x1f")
    return h.hexdigest()[:40]


STOPWORDS = set(
    ["a", "an", "the", "and", "or", "but", "if", "then", "of", "to", "in", "on", "at", "by", "for", "with", "from", "as", "is", "are", "was", "were", "be", "been", "it", "its", "this", "that", "these", "those", "i", "we", "you", "he", "she", "they", "me", "us", "him", "her", "them", "my", "our", "your", "his", "their", "will", "would", "should", "can", "could", "may", "might", "must", "shall", "do", "does", "did", "have", "has", "had", "not", "no", "so", "just", "also", "please", "thanks", "thank", "hi", "hello", "re", "fw", "fwd", "let", "lets", "get", "got", "about", "into", "over", "after", "before", "up", "out", "what", "which", "who", "when", "where", "why", "how", "all", "any", "some", "more", "most", "other", "such", "than", "too", "very", "s", "t", "ll", "ve", "d", "m"]
)

_WORD = re.compile(r"[a-z0-9][a-z0-9\-]+")


def content_words(text: str) -> set[str]:
    return {stem(w) for w in _WORD.findall(text.lower()) if w not in STOPWORDS and len(w) > 2}


def stem(word: str) -> str:
    """Tiny suffix stripper: enough to match 'proposal'/'proposals', 'reviewed'/'review'."""
    for suf in ("ations", "ation", "ings", "ing", "ed", "es", "s"):
        if word.endswith(suf) and len(word) - len(suf) >= 4:
            return word[: -len(suf)]
    return word
