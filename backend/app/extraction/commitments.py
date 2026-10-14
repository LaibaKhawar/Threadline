"""Commitment, request and completion detection.

Separates four things that look alike on the surface:

  "I'll send the deck by Friday."           -> commitment   (speaker, send, deck, Friday)
  "Maybe we can finish this next month."    -> intention    (hedged; status UNCERTAIN)
  "Can you review the contract by Monday?"  -> request      (addressee owes it to the speaker)
  "I sent it yesterday." / "Attached is…"   -> completion   (evidence that fulfils earlier promises)

Actors are symbolic until entity resolution: SPEAKER (author), ADDRESSEE (the reader) or a name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from app.extraction.schemas import CommitmentExtraction, CompletionSignal
from app.extraction.temporal import extract_temporal, first_deadline
from app.extraction.text import Sentence, split_sentences

SPEAKER = "SPEAKER"
ADDRESSEE = "ADDRESSEE"

_HEDGES = re.compile(
    r"\b(maybe|might|perhaps|possibly|hopefully|probably|ideally|not sure|i think we can|we could|i could|"
    r"try to|attempt to|if (?:i|we) (?:can|have time|get a chance)|if possible|at some point|sometime|"
    r"would like to|hope to|aim to|plan to look into)\b",
    re.IGNORECASE,
)
_NEGATION = re.compile(r"\b(won't|will not|can't|cannot|can not|not going to|unable to|no longer)\b", re.IGNORECASE)
_NON_ACTION = {
    "be", "need", "like", "love", "want", "remember", "know", "see", "find", "do", "hear", "talk", "chat",
    "admit", "say", "bet", "assume", "guess", "wait", "probably", "maybe", "keep", "have", "go",
    "believe", "imagine", "feel", "help", "make", "mind", "try",
}
_SOFT_ACTIONS = {"keep", "let", "follow", "circle", "check", "look", "loop", "get", "come"}
_ADVERBS = {"definitely", "also", "still", "then", "just", "quickly", "personally", "certainly", "again",
            "really", "now", "finally", "first", "happily", "gladly", "be", "able", "make", "sure", "to", "try",
            "please", "kindly", "both", "all"}
_FIRST_PERSON = re.compile(
    r"\b(?P<subj>I|we|We)\s*(?:'ll|’ll|\s+will|\s+shall|'m going to|’m going to|\s+am going to|'re going to|’re going to|"
    r"\s+are going to|\s+promise to|\s+commit to|\s+can(?=\s+have\b))\s+(?P<rest>.+)",
)
_NOUN_PHRASE = re.compile(
    r"\b(?:the|a|an|our|my|your)\s+((?:[\w\-]+\s){0,3}(?:document|doc|deck|proposal|report|contract|plan|spec|draft|"
    r"budget|estimate|numbers|invoice|runbook|summary|notes|design|brief|analysis|forecast|roadmap|agenda|slides|"
    r"PR|feedback|approval|quote|checklist|mockups|dataset|criteria|agreement))\b", re.IGNORECASE)
_HEDGED_MODAL = re.compile(r"\b(?:I|we|We)\s+(?:can|could|might|may|should)\s+(?:probably\s+|maybe\s+|possibly\s+)?(?P<rest>.+)")
_LET_ME = re.compile(r"\b(?:Let me|let me)\s+(?P<rest>.+)")
_THIRD_PERSON = re.compile(
    r"\b(?P<name>[A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+(?:said|says|mentioned|confirmed|promised|agreed|told me|noted)\s+"
    r"(?:that\s+)?(?:she|he|they|she'd|he'd|they'd)\s*(?:'ll|’ll|\s+will|\s+would|'d|\s+is going to|\s+was going to)\s+(?P<rest>.+)"
)
_THIRD_DIRECT = re.compile(
    r"(?:^|[,;:]\s*|\band\s+)(?P<name>[A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+(?:will|is going to|has promised to|promised to|agreed to|is on the hook to)\s+(?P<rest>.+)"
)
_REQUEST = re.compile(
    r"(?:^|[,;:]\s*|\b)(?:(?P<name>[A-Z][a-z]+),?\s+)?(?:can|could|would|will)\s+you(?:\s+please)?\s+(?P<rest>.+)",
    re.IGNORECASE,
)
_PLEASE = re.compile(r"(?:^|[,;:]\s*|\b(?:then|and)\s+)(?:(?P<name>[A-Z][a-z]+),?\s+)?please\s+(?P<rest>.+)", re.IGNORECASE)
_YOU_WILL = re.compile(r"\b(?:you'll|you will|you need to|you should)\s+(?P<rest>.+)", re.IGNORECASE)
_ACTION_ITEM = re.compile(
    r"^\s*(?:[-*•]|\d+[.)]|\[ \])?\s*(?:AI:|Action:|TODO:)?\s*(?P<name>[A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s*(?:to|:|—|-|will)\s+(?P<rest>.+)$"
)
_COMPLETED = re.compile(
    r"\b(?:(?P<subj>I|we|We)\s*(?:'ve|’ve|\s+have)?\s+(?:just\s+|already\s+|now\s+|finally\s+)?(?P<verb>sent|shared|attached|uploaded|"
    r"finished|completed|submitted|reviewed|approved|signed|delivered|published|merged|deployed|pushed|wrapped up|"
    r"done|resolved|fixed|closed|scheduled|booked|finalized|finalised|drafted|updated|written|wrote|prepared)\b)"
    r"|\b(?P<att>attached is|attached are|attached please find|please find attached|attaching|here is|here's|here are|"
    r"enclosed is|i've attached|sharing the|as promised)\b",
    re.IGNORECASE,
)
_CANCEL = re.compile(
    r"\b(no longer need|don't need|do not need|cancel(?:led|ling)?\s+(?:the|our|my|this)|scrap(?:ped|ping)?\s+the|"
    r"drop(?:ped|ping)?\s+the|never mind|nevermind|not needed anymore|no need to|won't be (?:sending|needing|doing)|"
    r"called off|put on hold|deprioriti[sz]ed|shelved)\b",
    re.IGNORECASE,
)
_DONE_PASSIVE = re.compile(
    r"\b(?:the\s+)?(?P<obj>[\w\-]+(?:\s[\w\-]+){0,5}?)\s+(?:is|are|has been|have been)\s+(?:now\s+)?"
    r"(?:done|complete|completed|finished|ready|live|signed|approved|merged|deployed|uploaded)\b", re.IGNORECASE)
STRONG_CANCEL = re.compile(r"\b(no longer need|not needed anymore|never mind|nevermind|called off|cancel)", re.I)
_REQUEST_NON_ACTIONS = {"use", "note", "find", "ignore", "disregard", "feel", "enjoy", "keep", "remember", "excuse",
                        "forgive", "welcome", "believe", "imagine", "advise"}
_OBJ_STOP = re.compile(
    r"\s+(?:by|before|on|until|no later than|first thing|early|later|asap|once|when|after|so that|so|"
    r"because|if|and|which|today|tomorrow|tonight|yesterday|this|next|last|end of|EOD|EOW|within|in time|sometime|soon|"
    r"later this|at some point|whenever|while|but)\b|\s+in\s+(?=[A-Z0-9]|the next|a few|two|three|time)"
    r"|[,.;:!?()]|\s+-\s+|\s+—\s+",
    re.IGNORECASE,
)
_LEADING_DET = re.compile(r"^(?:the|a|an|my|our|your|their|his|her|its|this|that|these|those|some)\s+", re.IGNORECASE)
_PRONOUN_OBJ = {"it", "this", "that", "them", "these", "those", "one", "everything", "something", "back"}
_DELIVER_VERBS = {"send", "share", "forward", "deliver", "submit", "email", "upload", "attach", "post", "circulate",
                  "provide", "give", "hand", "pass", "get"}

_VERB_CANON = {
    "have": "deliver", "get": "deliver", "pass": "send", "email": "send", "forward": "send",
    "circulate": "share", "hand": "deliver", "provide": "send", "give": "send", "put together": "prepare",
    "write up": "write", "look at": "review", "look over": "review", "go over": "review", "go through": "review",
    "get back": "reply", "circle back": "follow up", "loop back": "follow up", "check in": "follow up",
    "follow up": "follow up", "sign off": "approve", "set up": "set up", "wrap up": "finish", "finalise": "finalize",
}
_DETERMINERS = {"a", "an", "the", "it", "this", "that", "these", "those", "some", "my", "our", "your", "their", "his", "her", "any"}
_GERUND = {"sending": "send", "sharing": "share", "reviewing": "review", "writing": "write", "preparing": "prepare",
           "updating": "update", "finalizing": "finalize", "scheduling": "schedule", "running": "run", "getting": "get",
           "making": "make", "having": "have", "putting": "put", "setting": "set", "planning": "plan"}
_PHRASAL = ("put together", "write up", "look at", "look over", "go over", "go through", "get back", "circle back",
            "loop back", "check in", "follow up", "sign off", "set up", "wrap up", "send over", "send across",
            "send out", "send you", "send me", "get you", "get it", "share with", "let you know", "keep you posted")


@dataclass
class ExtractionContext:
    sent_at: datetime
    timezone: str = "UTC"
    subject: str = ""
    speaker_name: str | None = None
    addressee_names: tuple[str, ...] = ()
    known_people: tuple[str, ...] = ()
    source_kind: str = "email"  # email | meeting | note | document


def _parse_action(rest: str) -> tuple[str, str | None, str] | None:
    """Return (canonical action, object, raw verb phrase) from the text after the modal."""
    words = rest.strip().split()
    i = 0
    while i < len(words) and words[i].lower().strip(",") in _ADVERBS:
        if words[i].lower() == "be":
            nxt = words[i + 1].lower() if i + 1 < len(words) else ""
            if not (nxt.endswith("ing") or nxt == "able"):
                return None  # "we'll be back Tuesday" describes a state, not an action
        i += 1
    if i >= len(words):
        return None
    tail = " ".join(words[i:])
    low = tail.lower()
    if low.startswith("let you know") or low.startswith("keep you posted") or low.startswith("keep you updated"):
        obj = _clean_object(re.sub(r"^(let you know|keep you (?:posted|updated))\s*(?:about|on|whether|if|when|how)?\s*", "", tail, flags=re.I))
        return "update", obj, tail
    verb = None
    for ph in _PHRASAL:
        if low.startswith(ph + " ") or low == ph:
            verb = ph
            break
    if verb is None:
        verb = re.sub(r"[^a-z\-]", "", words[i].lower())
    if not verb or (verb in _NON_ACTION and verb not in ("have", "get")):
        return None
    after = tail[len(verb):].strip() if tail.lower().startswith(verb) else " ".join(words[i + 1 :])
    if verb in ("send over", "send across", "send out", "send you", "send me"):
        verb = "send"
    if verb in ("get you", "get it"):
        verb = "deliver"
    if verb in ("get back", "circle back", "loop back", "follow up", "check in"):
        after = re.sub(r"^(?:to|with)\s+(?:you|me|him|her|them|us|[A-Z][a-z]+)\s*", "", after)
        after = re.sub(r"^(?:on|about|re|regarding|with)\s+", "", after)
    if verb in ("check",):
        after = re.sub(r"^(?:with|on|in with)\s+", "", after)
    if verb == "share with":
        verb = "share"
        after = re.sub(r"^\w+\s*", "", after)  # drop the person after "share with"
    # "have the report to you" / "get the numbers over to you"
    if verb in _DETERMINERS or len(verb) < 2:
        return None
    if verb == "have":
        ready = re.match(r"(.+?)\s+(?:ready|done|finished|completed|wrapped up)\b", after)
        if ready:
            return "deliver", _clean_object(ready.group(1)), tail
    if verb in ("have", "get"):
        m = re.match(r"(.+?)\s+(?:over\s+)?(?:to|back to)\s+(?:you|me|him|her|them|\w+)\b", after)
        if not m:
            if verb == "have":
                return None
            m2 = re.match(r"(?:back\s+to\s+you|back)\b", after)
            if m2:
                return "reply", None, tail
        after = m.group(1) if m else after
    after = re.sub(r"^(?:you|me|him|her|them|us)\s+(?=\w)", "", after) if verb in ("send", "share", "forward", "email", "give") else after
    obj = _clean_object(after)
    canon = _VERB_CANON.get(verb, verb)
    if canon.endswith("ing") and len(canon) > 5:
        canon = _GERUND.get(canon, canon[:-3])
    return canon, obj, tail


def _clean_object(after: str) -> str | None:
    m = _OBJ_STOP.search(after)
    obj = after[: m.start()] if m else after
    obj = re.sub(r"\s+(?:to|with|for)\s+(?:you|me|him|her|them|us|everyone|the team)$", "", obj.strip(), flags=re.I)
    obj = re.sub(r"\s+(?:to|with|for)\s+[A-Z][a-z]+(?:\s[A-Z][a-z]+)?$", "", obj)
    obj = re.sub(r"\s+(?:over|across|out|back|along)$", "", obj, flags=re.I)
    obj = _LEADING_DET.sub("", obj.strip())
    obj = obj.strip(" '\"")
    return obj[:200] or None


def _resolve_pronoun(obj: str | None, ctx: ExtractionContext, previous_objects: list[str]) -> str | None:
    if obj is None:
        return previous_objects[-1] if previous_objects else None
    if obj.lower() in _PRONOUN_OBJ or obj.lower().startswith(("it ", "this ", "that ")):
        if previous_objects:
            return previous_objects[-1]
        from app.extraction.text import normalize_subject

        subj = normalize_subject(ctx.subject)
        return subj or obj
    return obj


def _recipient_from(text: str, default: str | None) -> str | None:
    m = re.search(r"\b(?:to|with|for)\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\b", text)
    if m and m.group(1) not in ("I", "We", "You", "Friday", "Monday", "Tuesday", "Wednesday", "Thursday", "Project"):
        return m.group(1)
    return default


def extract_commitments(text: str, ctx: ExtractionContext) -> list[CommitmentExtraction]:
    out: list[CommitmentExtraction] = []
    previous_objects: list[str] = []
    for sent in split_sentences(text):
        found = _from_sentence(sent, ctx, previous_objects, len(out))
        for c in found:
            if c.object and c.object.lower() not in _PRONOUN_OBJ:
                previous_objects.append(c.object)
        out.extend(found)
        # Keep the latest concrete noun phrase as antecedent for "it" in later sentences.
        if not found:
            previous_objects.extend(_NOUN_PHRASE.findall(sent.text)[-1:])
    return out


def _from_sentence(
    sent: Sentence, ctx: ExtractionContext, previous_objects: list[str], base_index: int
) -> list[CommitmentExtraction]:
    s = sent.text
    if s.endswith("?") and not _REQUEST.search(s):
        return []
    if _COMPLETED.search(s) and not re.search(r"\b(will|'ll|’ll|going to)\b", s):
        return []
    hedged = bool(_HEDGES.search(s))
    negated = bool(_NEGATION.search(s))
    results: list[CommitmentExtraction] = []
    deadline = first_deadline(s, ctx.sent_at, ctx.timezone)
    due_at = deadline.value if deadline else None
    due_text = deadline.text if deadline else None

    def make(kind: str, actor: str, rest: str, conf: float, recipient: str | None) -> None:
        parsed = _parse_action(rest)
        if not parsed:
            return
        action, obj, _ = parsed
        if kind == "request" and action in _REQUEST_NON_ACTIONS:
            return
        if action in _SOFT_ACTIONS and action not in ("follow up",):
            conf -= 0.1
        head = s[: s.find(rest[:20])] if rest[:20] in s else ""
        obj = _resolve_pronoun(obj, ctx, previous_objects + _NOUN_PHRASE.findall(head))
        if kind == "commitment" and hedged:
            kind, conf = "intention", min(conf, 0.45)
        if deadline:
            conf += 0.05
        depends = None
        if re.match(r"^(?:once|after|when)\b", s, re.IGNORECASE) and base_index + len(results) > 0:
            depends = base_index + len(results) - 1
        try:
            item = CommitmentExtraction(
                kind=kind,  # type: ignore[arg-type]
                actor=actor,
                action=action,
                object=obj,
                recipient=_recipient_from(rest, recipient),
                due_text=due_text,
                due_at=due_at,
                confidence=round(max(0.05, min(conf, 0.97)), 3),
                source_span=s,
                span_start=sent.start,
                span_end=sent.end,
                depends_on_index=depends,
            )
        except ValueError:  # pydantic ValidationError: a malformed parse is skipped, never fatal
            return
        results.append(item)

    if negated and not _REQUEST.search(s):
        return []

    if ctx.source_kind in ("meeting", "note"):
        m = _ACTION_ITEM.match(s)
        if m and m.group("name") not in ("I", "We", "You", "Project", "Decision", "Next", "Note", "Action"):
            make("commitment", m.group("name"), m.group("rest"), 0.8, None)
            return results

    m3 = _THIRD_PERSON.search(s)
    if m3:
        make("commitment", m3.group("name"), m3.group("rest"), 0.72, None)
        return results
    m = _FIRST_PERSON.search(s)
    if m:
        actor = SPEAKER
        make("commitment", actor, m.group("rest"), 0.86, ADDRESSEE)
        # "I'll send the doc, and once you've reviewed it, please…" continues below via other patterns
    else:
        m4 = _THIRD_DIRECT.search(s)
        if m4 and m4.group("name") not in ("I", "We", "You", "It", "This", "That", "Project", "Decision", "Next",
                                          "Everyone", "Nobody", "Someone", "The", "Who", "What", "Which", "There"):
            make("commitment", m4.group("name"), m4.group("rest"), 0.7, None)
        else:
            lm = _LET_ME.search(s)
            hm = _HEDGED_MODAL.search(s)
            if lm and not hedged:
                make("commitment", SPEAKER, lm.group("rest"), 0.7, ADDRESSEE)
            elif hm and hedged:
                make("intention", SPEAKER, hm.group("rest"), 0.4, ADDRESSEE)
                if results:
                    m = hm  # suppress request parsing for this sentence
    rq = _REQUEST.search(s)
    if rq and not m:
        actor = rq.group("name") if rq.group("name") and rq.group("name").lower() not in ("so", "and", "also", "then", "but") else ADDRESSEE
        make("request", actor, rq.group("rest").rstrip("?"), 0.74, SPEAKER)
    else:
        pl = _PLEASE.search(s)
        if pl and not re.search(r"please (?:find|see|note|let me know|ignore|disregard)", s, re.IGNORECASE):
            actor = pl.group("name") if pl.group("name") and pl.group("name").lower() not in ("so", "and", "also", "then", "but", "hi", "hey") else ADDRESSEE
            make("request", actor, pl.group("rest"), 0.72, SPEAKER)
        elif not m:
            yw = _YOU_WILL.search(s)
            if yw and not hedged:
                make("request", ADDRESSEE, yw.group("rest"), 0.6, SPEAKER)
    return results


def extract_completions(text: str, ctx: ExtractionContext) -> list[CompletionSignal]:
    out: list[CompletionSignal] = []
    for sent in split_sentences(text):
        s = sent.text
        cancel = _CANCEL.search(s)
        if cancel:
            obj = _clean_object(s[cancel.end():].strip()) or _clean_object(s[: cancel.start()].strip().split(" the ")[-1])
            out.append(CompletionSignal(actor=SPEAKER, action="cancel", object=obj, source_span=s,
                                        span_start=sent.start, span_end=sent.end, kind="cancelled"))
            continue
        if re.search(r"\b(will|'ll|’ll|going to|can you|could you)\b", s, re.IGNORECASE) or re.search(
            r"\bplease\b(?!\s+find)", s, re.IGNORECASE
        ):
            continue
        m = _COMPLETED.search(s)
        if not m:
            pm = _DONE_PASSIVE.search(s)
            if pm and not s.endswith("?"):
                out.append(CompletionSignal(actor=SPEAKER, action="finish", object=_clean_object(pm.group("obj")),
                                            source_span=s, span_start=sent.start, span_end=sent.end, kind="completed"))
            continue
        verb = (m.group("verb") or "send").lower()
        verb = {"sent": "send", "shared": "share", "attached": "send", "uploaded": "send", "finished": "finish",
                "completed": "finish", "submitted": "send", "reviewed": "review", "approved": "approve",
                "signed": "sign", "delivered": "send", "published": "publish", "merged": "merge",
                "deployed": "deploy", "pushed": "send", "wrapped up": "finish", "done": "finish",
                "resolved": "fix", "fixed": "fix", "closed": "finish", "scheduled": "schedule",
                "booked": "schedule", "finalized": "finalize", "finalised": "finalize", "drafted": "draft",
                "updated": "update", "written": "write", "wrote": "write", "prepared": "prepare"}.get(verb, verb)
        obj = _clean_object(s[m.end():].strip())
        out.append(CompletionSignal(actor=SPEAKER, action=verb, object=obj, source_span=s,
                                    span_start=sent.start, span_end=sent.end, kind="completed"))
    return out


def mentions_dates(text: str, ctx: ExtractionContext) -> list[tuple[int, int, str]]:
    return [(m.start, m.end, m.text) for m in extract_temporal(text, ctx.sent_at, ctx.timezone)]
