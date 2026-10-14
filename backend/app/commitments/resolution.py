"""Commitment resolution: decide whether a promise was kept, cancelled, is overdue, or is still open.

For each unresolved commitment, later content by the responsible person is scored as a possible
fulfilment. Signals are explicit and stored with the decision so the UI can show *why*:

  completion statement by the actor ("attached is", "I sent")    +0.30
  object word overlap with the commitment (stemmed)               up to +0.30
  semantic similarity of the statement to the commitment          up to +0.25
  attachment whose name matches the object / any attachment       +0.20 / +0.10
  same email thread as the promise                                +0.15
  sent to the person the promise was made to                      +0.10

  score >= 0.70             -> FULFILLED (with both source events as evidence)
  0.45 <= score < 0.70      -> kept as a *candidate* the user can confirm; status unchanged
  cancellation statement    -> CANCELLED when it refers to the same object/thread
  due date passed, no match -> OVERDUE, with an explanation of what was searched
Intentions (hedged statements) are never marked overdue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.embeddings.base import cosine, get_embedder
from app.core.timeutil import ensure_aware
from app.db import models as m
from app.extraction.commitments import STRONG_CANCEL, ExtractionContext, extract_completions
from app.extraction.text import content_words, split_signature, strip_quoted_reply
from app.ingestion.workspace import Workspace

FULFILL_THRESHOLD = 0.70
CANDIDATE_THRESHOLD = 0.45
OPEN_STATES = ("OPEN", "OVERDUE", "UNCERTAIN")
_DELIVER = {"send", "share", "deliver", "upload", "update", "write", "draft", "prepare", "finish", "finalize",
            "publish", "submit", "reply", "provide", "circulate", "post"}
GENERIC_OBJECT_WORDS = {"document", "doc", "deck", "report", "note", "file", "plan", "update", "draft", "version",
                        "final", "new", "first", "updat", "project", "atlas", "phoenix", "orion"}
_REPLY_ACTIONS = {"confirm", "reply", "answer", "respond", "clarify", "tell", "update", "let"}
_APPROVAL_YES = ("approved", "approve it", "go ahead", "signed off", "sign off", "green light", "greenlit", "you have my approval")
_APPROVAL_NO = ("not approved", "can't approve", "cannot approve", "rejected", "declined", "decline", "not able to approve")


@dataclass
class Candidate:
    source_type: str
    source_id: str
    occurred_at: datetime
    author_pid: str | None
    text: str
    title: str
    thread_id: str | None = None
    to_pids: set[str] = field(default_factory=set)
    attachments: list[str] = field(default_factory=list)
    cancel_only: bool = False
    project_id: str | None = None


def _compatible(a: str, b: str) -> bool:
    if a == b:
        return True
    if a in _DELIVER and b in _DELIVER:
        return True
    if a == "finish" or b == "finish":  # "the review is done" completes "run the security review"
        return True
    return {a, b} <= {"review", "finish"} or {a, b} <= {"approve", "sign"} or {a, b} <= {"fix", "finish"}


def _completions(cand: Candidate, cache: dict[str, Any]) -> list[Any]:
    key = f"comps:{cand.source_type}:{cand.source_id}"
    if key not in cache:
        cache[key] = extract_completions(cand.text, ExtractionContext(sent_at=cand.occurred_at, subject=cand.title))
    return cache[key]  # type: ignore[no-any-return]


def could_resolve(c: m.Commitment, cand: Candidate, commit_thread: str | None, cache: dict[str, Any]) -> bool:
    """Cheap gate. Without a delivery/cancellation statement, an attachment, an approval answer or a reply in the
    same thread, score_candidate caps the score at 0.40 (below every threshold), so scoring can be skipped."""
    if _completions(cand, cache) or cand.attachments:
        return True
    low = cand.text.lower()
    if any(p in low for p in _APPROVAL_YES + _APPROVAL_NO):
        return True
    return c.action in _REPLY_ACTIONS and bool(commit_thread) and cand.thread_id == commit_thread


def score_candidate(c: m.Commitment, cand: Candidate, *, commit_thread: str | None, embed_cache: dict[str, Any]) -> tuple[float, dict[str, Any], str]:
    """Return (score, signals, outcome) where outcome is 'fulfilled-signal' | 'cancelled' | 'none'."""
    signals: dict[str, Any] = {}
    obj_words = content_words(c.object or "") or content_words(c.description)
    comps = _completions(cand, embed_cache)
    text_words = content_words(f"{cand.title} {cand.text}")
    distinctive = obj_words - GENERIC_OBJECT_WORDS
    for comp in comps:
        if comp.kind == "cancelled":
            ov = (distinctive or obj_words) & content_words(f"{comp.object or ''} {comp.source_span}")
            ratio = len(ov) / len(distinctive or obj_words) if (distinctive or obj_words) else 0.0
            same_thread = bool(commit_thread and cand.thread_id == commit_thread)
            if ratio >= 0.5 or (same_thread and STRONG_CANCEL.search(comp.source_span) and not distinctive):
                signals["cancellation"] = comp.source_span
                signals["object_overlap"] = sorted(ov)
                return 0.8, signals, "cancelled"
    score = 0.0
    best_span = None
    for comp in comps:
        if comp.kind != "completed":
            continue
        base = distinctive or obj_words
        delivered = content_words(comp.object or "")
        strong_overlap = bool(base) and len(base & delivered) / len(base) >= 0.6
        # "Here are the funnel numbers" fulfils "pull the funnel numbers": delivering the object counts.
        if _compatible(comp.action, c.action) or (comp.action in _DELIVER and strong_overlap):
            comp_words = content_words(f"{comp.object or ''} {comp.source_span}")
            about_it = bool((distinctive or obj_words) & comp_words) or comp.object is None
            comp_obj = content_words(comp.object or "") - GENERIC_OBJECT_WORDS
            # "pilot proposal" vs "Phoenix proposal": each side has a qualifier the other lacks.
            if distinctive - comp_obj and comp_obj - obj_words and len(distinctive & comp_obj) < len(distinctive):
                about_it = False
                signals["conflicting_object"] = sorted(comp_obj - obj_words)
            score += 0.30 if about_it else 0.10
            best_span = comp.source_span
            signals["completion_statement"] = comp.source_span
            if not about_it:
                signals["completion_about_other_object"] = True
            break
    if (c.action in _REPLY_ACTIONS and cand.author_pid == c.actor_person_id and commit_thread
            and cand.thread_id == commit_thread):
        score += 0.45
        signals["replied_in_thread"] = True
    if c.action in ("approve", "sign") or "approv" in (c.object or "").lower():
        low = cand.text.lower()
        if any(p in low for p in _APPROVAL_NO):
            score += 0.30
            signals["approval_answer"] = "rejected"
        elif any(p in low for p in _APPROVAL_YES):
            score += 0.30
            signals["approval_answer"] = "approved"
    if obj_words:
        hay = content_words(best_span or "") | text_words
        ratio = len(obj_words & hay) / len(obj_words)
        if ratio:
            score += round(0.30 * ratio, 3)
            signals["object_overlap"] = sorted(obj_words & hay)
    key = c.id
    if key not in embed_cache:
        embed_cache[key] = get_embedder().embed_one(f"{c.action} {c.object or c.description}", query=True)
    probe = best_span or f"{cand.title}. {cand.text[:400]}"
    pkey = "probe:" + probe[:500]
    if pkey not in embed_cache:  # the same email is a candidate for many commitments: embed it once per pass
        embed_cache[pkey] = get_embedder().embed_one(probe)
    sim = cosine(embed_cache[key], embed_cache[pkey])
    signals["semantic_similarity"] = round(sim, 3)
    if sim > 0.5:
        score += min(0.25, round((sim - 0.5) * 0.8, 3))
    def _att_match(a: str) -> bool:
        aw = content_words(a.rsplit(".", 1)[0].replace("_", " ").replace("-", " "))
        base = distinctive or obj_words
        return bool(base) and len(base & aw) / len(base) >= 0.6

    att_hit = [a for a in cand.attachments if _att_match(a)]
    if att_hit:
        score += 0.20
        signals["matching_attachment"] = att_hit[0]
    elif cand.attachments and c.action in _DELIVER:
        score += 0.10
        signals["attachment"] = cand.attachments[0]
    if commit_thread and cand.thread_id == commit_thread:
        score += 0.15
        signals["same_thread"] = True
    if c.project_id and cand.project_id and c.project_id != cand.project_id:
        score -= 0.3
        signals["different_project"] = True
    if c.recipient_person_id and c.recipient_person_id in cand.to_pids:
        score += 0.10
        signals["sent_to_recipient"] = True
    strong = ("approval_answer" in signals or "matching_attachment" in signals or "replied_in_thread" in signals
              or ("completion_statement" in signals and "completion_about_other_object" not in signals))
    if not strong:
        score = min(score, 0.40)  # no delivery statement, artifact or reply: not even a candidate
    return round(min(score, 0.99), 3), signals, "fulfilled-signal"


def _candidate_for(db: Session, user_id: str, ref: tuple[str, str]) -> Candidate | None:
    st, sid = ref
    if st == "email":
        e = db.get(m.Email, sid)
        if e is None or e.user_id != user_id:
            return None
        body, _ = split_signature(strip_quoted_reply(e.body or ""))
        to = set(db.scalars(select(m.Relationship.dst_id).where(m.Relationship.user_id == user_id, m.Relationship.src_id == e.id,
                                                                m.Relationship.rel_type == "SENT_TO")))
        return Candidate("email", e.id, e.sent_at, e.sender_person_id, body, e.subject, e.thread_id, to,
                         [a.get("filename", "") for a in (e.attachments or [])], project_id=e.project_id)
    if st == "document":
        d = db.get(m.Document, sid)
        if d is None or d.user_id != user_id:
            return None
        when = ensure_aware(d.authored_at) or d.created_at
        return Candidate("document", d.id, when, d.author_person_id, d.text[:1500], d.title, attachments=[d.original_filename],
                         project_id=d.project_id)
    if st == "event":
        ev = db.get(m.CalendarEvent, sid)
        if ev is None or ev.user_id != user_id or not ev.notes:
            return None
        return Candidate("event", ev.id, ev.end_at, None, ev.notes, ev.title, project_id=ev.project_id)
    return None


def _email_candidates(db: Session, user_id: str, author_pid: str, after: datetime, limit: int = 40) -> list[Candidate]:
    out = []
    for e in db.scalars(select(m.Email).where(m.Email.user_id == user_id, m.Email.sender_person_id == author_pid,
                                              m.Email.sent_at > after).order_by(m.Email.sent_at).limit(limit)):
        body, _ = split_signature(strip_quoted_reply(e.body or ""))
        to = set()
        for r in db.scalars(select(m.Relationship.dst_id).where(m.Relationship.user_id == user_id, m.Relationship.src_id == e.id,
                                                                m.Relationship.rel_type == "SENT_TO")):
            to.add(r)
        out.append(Candidate("email", e.id, e.sent_at, author_pid, body, e.subject, e.thread_id, to,
                             [a.get("filename", "") for a in (e.attachments or [])], project_id=e.project_id))
    return out


def _meeting_candidates(db: Session, user_id: str, author_pid: str, after: datetime, until: datetime) -> list[Candidate]:
    out = []
    q = (select(m.CalendarEvent).join(m.EventParticipant, m.EventParticipant.event_id == m.CalendarEvent.id)
         .where(m.CalendarEvent.user_id == user_id, m.EventParticipant.person_id == author_pid,
                m.CalendarEvent.start_at > after, m.CalendarEvent.start_at <= until, m.CalendarEvent.notes.is_not(None)))
    for ev in db.scalars(q):
        out.append(Candidate("event", ev.id, ev.end_at, author_pid, ev.notes or "", ev.title, project_id=ev.project_id))
    return out


def _document_candidates(db: Session, user_id: str, author_pid: str, after: datetime) -> list[Candidate]:
    out = []
    for d in db.scalars(select(m.Document).where(m.Document.user_id == user_id, m.Document.author_person_id == author_pid,
                                                 m.Document.authored_at > after)):
        when = ensure_aware(d.authored_at) or d.created_at
        if when and when > after:
            out.append(Candidate("document", d.id, when, author_pid, d.text[:1500], d.title, attachments=[d.original_filename],
                                 project_id=d.project_id))
    return out


def resolve_commitments(ws: Workspace, *, only_source: tuple[str, str] | None = None,
                        actor_pid: str | None = None) -> dict[str, int]:
    db = ws.db
    now = ws.now()
    stats = {"checked": 0, "fulfilled": 0, "cancelled": 0, "candidates": 0, "overdue": 0}
    embed_cache: dict[str, Any] = {}
    one: Candidate | None = None
    if only_source is not None:
        one = _candidate_for(db, ws.user_id, only_source)
        if one is None:
            return stats
        low = one.text.lower()
        if not (_completions(one, embed_cache) or one.attachments or one.thread_id
                or any(p in low for p in _APPROVAL_YES + _APPROVAL_NO)):
            return stats  # this item cannot fulfil, cancel or answer anything
    q = select(m.Commitment).where(m.Commitment.user_id == ws.user_id, m.Commitment.status.in_(OPEN_STATES))
    if actor_pid:
        q = q.where(m.Commitment.actor_person_id == actor_pid)
    commitments = list(db.scalars(q))
    for c in commitments:
        stats["checked"] += 1
        if c.user_confirmed or c.user_modified:
            continue  # the user set this status/date by hand; automatic resolution never overrides it
        detected = ensure_aware(c.detected_at)
        assert detected is not None
        commit_thread = None
        if c.source_type == "email":
            src_email = db.get(m.Email, c.source_id)
            commit_thread = src_email.thread_id if src_email else None
        cands: list[Candidate] = []
        if only_source is not None:
            # Incremental pass (one new item arrived): score just that item. Full candidate scans and overdue
            # checks happen in the end-of-sync / scheduled pass, which keeps ingestion linear in the number of items.
            if one is None or ensure_aware(one.occurred_at) <= detected:  # type: ignore[operator]
                continue
            cands = [one]
        elif c.actor_person_id:
            cands += _email_candidates(db, ws.user_id, c.actor_person_id, detected)
            cands += _meeting_candidates(db, ws.user_id, c.actor_person_id, detected, now)
            cands += _document_candidates(db, ws.user_id, c.actor_person_id, detected)
        # The person the promise was made to can cancel it ("we no longer need the deck").
        if c.recipient_person_id and c.recipient_person_id != c.actor_person_id and only_source is None:
            for x in _email_candidates(db, ws.user_id, c.recipient_person_id, detected):
                x.cancel_only = True
                cands.append(x)
        # Meeting notes may report that someone else delivered ("Ahmed shared the runbook").
        cands = [x for x in cands if ensure_aware(x.occurred_at) <= now]  # type: ignore[operator]
        best: tuple[float, Candidate, dict[str, Any], str] | None = None
        for cand in cands:
            if cand.source_id == c.source_id:
                continue
            if not could_resolve(c, cand, commit_thread, embed_cache):
                continue
            score, signals, outcome = score_candidate(c, cand, commit_thread=commit_thread, embed_cache=embed_cache)
            if cand.cancel_only and outcome != "cancelled":
                continue
            if best is None or score > best[0] or outcome == "cancelled":
                best = (score, cand, signals, outcome)
                if outcome == "cancelled":
                    break
        if best and best[3] == "cancelled":
            _record(ws, c, best, "cancelled")
            c.status, c.resolved_at = "CANCELLED", best[1].occurred_at
            c.resolution_reason = f"Cancelled: “{best[2].get('cancellation')}”"
            stats["cancelled"] += 1
            continue
        if best and best[0] >= FULFILL_THRESHOLD:
            _record(ws, c, best, "fulfilled")
            c.status = "FULFILLED"
            stats["fulfilled"] += 1
            continue
        if best and best[0] >= CANDIDATE_THRESHOLD:
            _record(ws, c, best, "candidate")
            stats["candidates"] += 1
        due = ensure_aware(c.due_at)
        if only_source is not None:
            continue
        if c.status in ("OPEN", "OVERDUE") and c.kind != "intention" and due and due < now:
            if c.status == "OPEN":
                stats["overdue"] += 1
            c.status = "OVERDUE"
            who = _name(db, c.actor_person_id) or c.actor_text or "the responsible person"
            searched = f"{len([x for x in cands if not x.cancel_only])} later item(s) from {who}"
            maybe = ""
            if best and best[0] >= CANDIDATE_THRESHOLD:
                maybe = f" A possible match scored {best[0]:.0%} (below the {FULFILL_THRESHOLD:.0%} needed to mark it fulfilled): “{best[1].title}”."
            elif best:
                maybe = f" The closest item scored {best[0]:.0%}."
            c.resolution_reason = (f"Expected by {_d(due)}; no later email, meeting note or document from {who} appears to "
                                   f"satisfy it ({searched} checked).{maybe}")
        elif c.status == "OVERDUE" and due and due >= now:
            c.status = "OPEN"
    return stats


def _record(ws: Workspace, c: m.Commitment, best: tuple[float, Candidate, dict[str, Any], str], outcome: str) -> None:
    db = ws.db
    score, cand, signals, _ = best
    fc = db.scalar(select(m.FulfillmentCandidate).where(m.FulfillmentCandidate.commitment_id == c.id,
                                                        m.FulfillmentCandidate.source_id == cand.source_id))
    if fc is None:
        fc = m.FulfillmentCandidate(user_id=ws.user_id, commitment_id=c.id, source_type=cand.source_type,
                                    source_id=cand.source_id, score=score, signals=signals, outcome=outcome)
        db.add(fc)
    elif fc.outcome == "rejected":  # the user said this is not the fulfilment
        return
    else:
        fc.score, fc.signals, fc.outcome = score, signals, outcome
    if outcome == "candidate":
        c.resolution_source_type, c.resolution_source_id, c.resolution_confidence = cand.source_type, cand.source_id, score
        c.resolution_reason = f"Possible fulfilment ({score:.0%}): {cand.title}"
        return
    c.resolution_source_type, c.resolution_source_id = cand.source_type, cand.source_id
    c.resolution_confidence, c.resolved_at = score, cand.occurred_at
    if outcome == "fulfilled":
        parts = []
        if "completion_statement" in signals:
            parts.append(f"completion statement “{signals['completion_statement'][:120]}”")
        if "approval_answer" in signals:
            parts.append(f"approval answer ({signals['approval_answer']})")
        if "object_overlap" in signals:
            parts.append("mentions " + ", ".join(signals["object_overlap"][:4]))
        if "matching_attachment" in signals:
            parts.append(f"attachment {signals['matching_attachment']}")
        if signals.get("same_thread"):
            parts.append("same thread")
        c.resolution_reason = f"Matched ({score:.0%}): " + "; ".join(parts)
    db.add(m.Evidence(user_id=ws.user_id, subject_type="commitment", subject_id=c.id, source_type=cand.source_type,
                      source_id=cand.source_id, span=signals.get("completion_statement") or signals.get("cancellation") or cand.title,
                      observed_at=cand.occurred_at, confidence=score, role="fulfillment" if outcome == "fulfilled" else "change"))
    ws.graph.add_edge(("commitment", c.id), "FULFILLED_BY" if outcome == "fulfilled" else "CANCELLED_BY",
                      (cand.source_type, cand.source_id), valid_from=cand.occurred_at, observed_at=cand.occurred_at,
                      confidence=score, source=(cand.source_type, cand.source_id), origin="extraction")
    from app.ingestion.processor import _timeline

    _timeline(ws, cand.occurred_at, f"commitment_{outcome}", f"{'Fulfilled' if outcome == 'fulfilled' else 'Cancelled'}: {c.description}",
              c.resolution_reason, ("commitment", c.id), c.project_id, [p for p in [c.actor_person_id] if p])


def _d(dt: datetime) -> str:
    return dt.strftime("%b %d, %Y").replace(" 0", " ")


def _name(db: Session, pid: str | None) -> str | None:
    p = db.get(m.Person, pid) if pid else None
    return p.display_name if p else None


_ = timedelta
