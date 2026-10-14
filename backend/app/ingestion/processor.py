"""Content processing pipeline (runs as the SourceItemUpserted event handler).

    normalise -> resolve participants -> structural graph edges -> extract (rules [+ LLM])
      -> resolve mentioned entities -> persist commitments / decisions / temporal facts with evidence
      -> associate project -> chunk + embed -> timeline + episodic memory

Every derived row is keyed deterministically (dedupe_key / unique edges), so reprocessing the same
source is idempotent, and rows the user has corrected are never overwritten.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.timeutil import ensure_aware
from app.db import models as m
from app.documents.chunking import ChunkSpec, chunk_plain
from app.extraction.commitments import ADDRESSEE, SPEAKER, ExtractionContext, extract_commitments, extract_completions
from app.extraction.decisions import extract_blockers, extract_deadline_changes, extract_decisions, extract_employment
from app.extraction.entities import extract_orgs, extract_people, extract_projects, org_from_domain
from app.extraction.schemas import CommitmentExtraction, DecisionExtraction, ExtractionResult
from app.extraction.text import content_words, normalize_subject, split_signature, stable_hash, strip_quoted_reply
from app.ingestion.workspace import Workspace
from app.intelligence.project_association import associate
from app.retrieval.indexer import index_chunks

log = get_logger(__name__)


AUTO_TASK_MIN_CONFIDENCE = 0.75  # with auto-create on, lower-confidence detections still need confirmation


@dataclass
class SourceCtx:
    """Everything the shared extraction step needs to know about one source item."""

    source_type: str  # email | event | document | note
    source_id: str
    title: str
    text: str  # cleaned text used for extraction
    occurred_at: datetime
    integration_id: str | None
    speaker_pid: str | None = None
    addressee_pids: list[str] = field(default_factory=list)
    participant_pids: set[str] = field(default_factory=set)
    project_id: str | None = None
    thread_id: str | None = None
    signature: str = ""
    source_kind: str = "email"


# ============================================================================ entry point


def process_source_item(db: Session, source_item_id: str) -> None:
    si = db.get(m.SourceItem, source_item_id)
    if si is None or si.deleted_at is not None:
        return
    ws = Workspace(db, si.user_id)
    try:
        if si.kind == "email":
            email = db.scalar(select(m.Email).where(m.Email.source_item_id == si.id))
            if email:
                process_email(ws, email, si.integration_id)
        elif si.kind == "event":
            ev = db.scalar(select(m.CalendarEvent).where(m.CalendarEvent.source_item_id == si.id))
            if ev:
                process_meeting(ws, ev, si.integration_id)
        elif si.kind == "document":
            doc = db.scalar(select(m.Document).where(m.Document.source_item_id == si.id))
            if doc:
                process_document(ws, doc, si.integration_id)
        elif si.kind == "note":
            note = db.scalar(select(m.Note).where(m.Note.source_item_id == si.id))
            if note:
                process_note(ws, note, si.integration_id)
        si.processing_status, si.processing_error = "done", None
    except Exception as exc:
        si.processing_status, si.processing_error = "error", f"{type(exc).__name__}: {str(exc)[:400]}"
        raise


# ============================================================================ emails


def _thread_for(ws: Workspace, email: m.Email) -> m.EmailThread:
    db = ws.db
    refs = [r for r in [email.in_reply_to, *(email.references or [])] if r]
    if refs:
        parent = db.scalar(select(m.Email).where(m.Email.user_id == ws.user_id, m.Email.message_id.in_(refs),
                                                 m.Email.thread_id.is_not(None)).limit(1))
        if parent and parent.thread_id:
            t = db.get(m.EmailThread, parent.thread_id)
            if t:
                return t
    key = stable_hash("subject", normalize_subject(email.subject).lower())
    t = db.scalar(select(m.EmailThread).where(m.EmailThread.user_id == ws.user_id, m.EmailThread.thread_key == key))
    if t is None:
        t = m.EmailThread(user_id=ws.user_id, thread_key=key, subject=normalize_subject(email.subject) or "(no subject)",
                          first_at=email.sent_at, last_at=email.sent_at, message_count=0)
        db.add(t)
        db.flush()
    return t


def process_email(ws: Workspace, email: m.Email, integration_id: str | None) -> None:
    db, g = ws.db, ws.graph
    thread = _thread_for(ws, email)
    email.thread_id = thread.id
    thread.first_at = min(filter(None, [thread.first_at, email.sent_at]))
    thread.last_at = max(filter(None, [thread.last_at, email.sent_at]))
    thread.message_count = db.query(m.Email).filter(m.Email.thread_id == thread.id).count()

    # --- participants
    src = ("email", email.id)
    sender = ws.resolver.resolve_person(email.from_name, email.from_addr, source=src)
    email.sender_person_id = sender.person_id
    email.direction = "outbound" if email.from_addr.lower() in ws.self_emails else "inbound"
    recips: list[tuple[str, str]] = []
    context_ids = {pid for pid in [sender.person_id] if pid}
    for role, lst in (("to", email.to_addrs or []), ("cc", email.cc_addrs or [])):
        for r in lst:
            res = ws.resolver.resolve_person(r.get("name"), r.get("email"), source=src, context_ids=context_ids)
            if res.person_id:
                recips.append((res.person_id, role))
                context_ids.add(res.person_id)
    if sender.person_id:
        g.add_edge(("person", sender.person_id), "SENT", src, valid_from=email.sent_at, observed_at=email.sent_at,
                   origin="structural", source=src)
        p = db.get(m.Person, sender.person_id)
        if p and not p.is_self:
            p.last_interaction_at = max(filter(None, [ensure_aware(p.last_interaction_at), email.sent_at]))
        _domain_employment(ws, sender.person_id, email.from_addr, email.sent_at, src)
    for pid, role in recips:
        g.add_edge(src, "SENT_TO", ("person", pid), valid_from=email.sent_at, observed_at=email.sent_at,
                   properties={"role": role}, origin="structural", source=src)
        if sender.person_id and pid != sender.person_id:
            g.add_edge(("person", sender.person_id), "KNOWS", ("person", pid), valid_from=email.sent_at,
                       observed_at=email.sent_at, origin="structural", confidence=0.6)
        if email.direction == "outbound":
            p = db.get(m.Person, pid)
            if p and not p.is_self:
                p.last_interaction_at = max(filter(None, [ensure_aware(p.last_interaction_at), email.sent_at]))
    g.add_edge(src, "PART_OF", ("thread", thread.id), observed_at=email.sent_at, origin="structural")

    # --- attachments reference documents with the same file name
    for att in email.attachments or []:
        fname = (att.get("filename") or "").lower()
        if not fname:
            continue
        doc = db.scalar(select(m.Document).where(m.Document.user_id == ws.user_id,
                                                 m.Document.original_filename.ilike(fname)).limit(1))
        if doc:
            g.add_edge(src, "REFERENCES", ("document", doc.id), observed_at=email.sent_at, origin="structural",
                       properties={"via": "attachment"})

    # --- text for extraction: no quoted history; signature kept aside for employment facts
    body = strip_quoted_reply(email.body or "")
    main, signature = split_signature(body)
    addressees = [pid for pid, role in recips if role == "to"] or [pid for pid, _ in recips]
    ctx = SourceCtx(
        source_type="email", source_id=email.id, title=email.subject, text=main, occurred_at=email.sent_at,
        integration_id=integration_id, speaker_pid=sender.person_id, addressee_pids=addressees,
        participant_pids=context_ids, thread_id=thread.id, signature=signature, source_kind="email",
    )
    # greeting names the actual addressee in multi-recipient emails ("Hi Laiba, ...")
    gm = re.match(r"\s*(?:Hi|Hello|Hey|Dear)\s+([A-Z][a-z]+)", main)
    if gm:
        res = ws.resolver.resolve_person(gm.group(1), context_ids=context_ids, create=False)
        if res.person_id:
            ctx.addressee_pids = [res.person_id, *[a for a in ctx.addressee_pids if a != res.person_id]]

    # --- project association (thread-level corrections are rules)
    project_pid, _ = associate(db, ws.user_id, subject_type="email", subject_id=email.id, title=email.subject, body=main,
                       participant_ids=context_ids, thread_project_id=thread.project_id,
                       rule_keys=[f"thread:{thread.id}", f"sender:{email.from_addr.lower()}"])
    email.project_id = project_pid
    if project_pid:
        thread.project_id = thread.project_id or project_pid
        g.add_edge(src, "BELONGS_TO", ("project", project_pid), observed_at=email.sent_at, origin="extraction", confidence=0.8)
        _project_members(ws, project_pid, context_ids)
    ctx.project_id = project_pid

    run_extraction(ws, ctx)
    email.importance = _importance(ws, email, ctx)

    header = f"Email from {email.from_name or email.from_addr} — {email.subject}\n"
    specs = chunk_plain(main or email.subject)
    index_chunks(db, user_id=ws.user_id, owner_type="email", owner_id=email.id, title=email.subject, specs=specs,
                 occurred_at=email.sent_at, project_id=project_pid, integration_id=integration_id, header=header)


def _importance(ws: Workspace, email: m.Email, ctx: SourceCtx) -> float:
    score = 0.4
    if email.direction == "inbound" and ws.self_person_id in ctx.addressee_pids:
        score += 0.15
    n_commit = ws.db.query(m.Commitment).filter(m.Commitment.source_id == email.id).count()
    score += min(0.3, 0.1 * n_commit)
    if re.search(r"\b(urgent|asap|blocker|blocked|deadline|today)\b", f"{email.subject} {ctx.text}", re.I):
        score += 0.15
    if re.search(r"\b(unsubscribe|newsletter|digest|no-reply|noreply)\b", f"{email.from_addr} {ctx.text}", re.I):
        score -= 0.3
    return round(max(0.0, min(1.0, score)), 2)


_BULK_SENDER = re.compile(r"^(?:digest|newsletter|news|no-?reply|notifications?|updates|marketing|mailer)[@.+]", re.I)


def _domain_employment(ws: Workspace, person_id: str, addr: str, at: datetime, src: tuple[str, str]) -> None:
    domain = addr.split("@")[1].lower() if "@" in addr else ""
    if not org_from_domain(domain) or _BULK_SENDER.match(addr):
        return
    p = ws.db.get(m.Person, person_id)
    if p is None or p.is_self:
        return
    org = ws.resolver.resolve_org(None, domain)
    if org is None:
        return
    # one structural edge per (person, org): valid_from = earliest email seen from that domain
    edge = ws.graph.add_edge(("person", person_id), "WORKS_AT", ("organization", org.id), valid_from=at,
                             observed_at=at, confidence=0.6, origin="structural",
                             properties={"basis": f"emails from @{domain}"})
    if edge.valid_from and at < ensure_aware(edge.valid_from):  # type: ignore[operator]
        edge.valid_from = at
        ws.graph._apply_functional(edge)
    _refresh_current_org(ws, person_id)


def _refresh_current_org(ws: Workspace, person_id: str) -> None:
    current = ws.db.scalar(select(m.Relationship).where(
        m.Relationship.user_id == ws.user_id, m.Relationship.src_type == "person", m.Relationship.src_id == person_id,
        m.Relationship.rel_type == "WORKS_AT", m.Relationship.status == "active").order_by(m.Relationship.valid_from.desc()))
    p = ws.db.get(m.Person, person_id)
    if p and current:
        p.organization_id = current.dst_id


def _project_members(ws: Workspace, project_id: str, people: set[str]) -> None:
    """Infer membership once a person has taken part in at least two items that belong to the project."""
    from sqlalchemy import and_, func, or_

    R = m.Relationship
    items = select(R.src_id).where(R.user_id == ws.user_id, R.rel_type == "BELONGS_TO", R.dst_id == project_id,
                                   R.src_type.in_(["email", "event"])).scalar_subquery()
    for pid in people:
        if pid == ws.self_person_id or ws.db.get(m.ProjectMember, (project_id, pid)) is not None:
            continue
        n = ws.db.scalar(select(func.count()).select_from(R).where(R.user_id == ws.user_id, or_(
            and_(R.rel_type == "SENT", R.src_id == pid, R.dst_id.in_(items)),
            and_(R.rel_type == "SENT_TO", R.dst_id == pid, R.src_id.in_(items)),
            and_(R.rel_type == "PARTICIPATES_IN", R.src_id == pid, R.dst_id.in_(items)),
        ))) or 0
        if n >= 2:
            ws.db.add(m.ProjectMember(project_id=project_id, person_id=pid, source="inferred"))
            ws.db.flush()
            ws.graph.add_edge(("person", pid), "PARTICIPATES_IN", ("project", project_id), origin="structural",
                              confidence=0.7, properties={"basis": f"in {n} project items"})


# ============================================================================ meetings


def process_meeting(ws: Workspace, ev: m.CalendarEvent, integration_id: str | None) -> None:
    db, g = ws.db, ws.graph
    src = ("event", ev.id)
    participants: set[str] = set()
    for a in ev.attendees or []:
        res = ws.resolver.resolve_person(a.get("name"), a.get("email"), source=src, context_ids=participants)
        if res.person_id:
            participants.add(res.person_id)
            if db.get(m.EventParticipant, (ev.id, res.person_id)) is None:
                db.add(m.EventParticipant(event_id=ev.id, person_id=res.person_id, response=a.get("response")))
            g.add_edge(("person", res.person_id), "PARTICIPATES_IN", src, valid_from=ev.start_at,
                       observed_at=ev.start_at, origin="structural", source=src)
            if a.get("email"):
                _domain_employment(ws, res.person_id, a["email"], ev.start_at, src)
    text = "\n\n".join(x for x in [ev.description or "", ev.notes or ""] if x)
    pid, _ = associate(db, ws.user_id, subject_type="event", subject_id=ev.id, title=ev.title, body=text,
                       participant_ids=participants, rule_keys=[f"event_title:{normalize_subject(ev.title).lower()}"])
    ev.project_id = pid
    if pid:
        g.add_edge(src, "BELONGS_TO", ("project", pid), observed_at=ev.start_at, confidence=0.8)
        _project_members(ws, pid, participants)
    if ev.location:
        g.add_edge(src, "OCCURRED_AT", ("topic", _topic(ws, f"location: {ev.location}").id), observed_at=ev.start_at,
                   origin="structural")
    organizer = None
    if ev.organizer:
        organizer = ws.resolver.resolve_person(None, ev.organizer, create=False).person_id
    # Notes are only processed for meetings that have happened.
    has_notes = bool(ev.notes and ev.notes.strip())
    ctx = SourceCtx(source_type="event", source_id=ev.id, title=ev.title, text=text, occurred_at=ev.end_at if has_notes else ev.start_at,
                    integration_id=integration_id, speaker_pid=organizer, addressee_pids=list(participants - {organizer} if organizer else participants),
                    participant_pids=participants, project_id=pid, source_kind="meeting")
    if text.strip():
        run_extraction(ws, ctx)
    _timeline(ws, ev.start_at, "meeting", ev.title, (ev.description or "")[:300], src, pid, list(participants))
    if has_notes:
        ws.memory.record_episode(content=f"Meeting “{ev.title}” on {ev.start_at.date().isoformat()}", occurred_at=ev.start_at,
                                 subject=("project", pid) if pid else None, source=src)
    header = f"Meeting: {ev.title} ({ev.start_at.date().isoformat()})\n"
    specs = chunk_plain(f"{ev.title}\n\n{text}" if text else ev.title)
    index_chunks(db, user_id=ws.user_id, owner_type="event", owner_id=ev.id, title=ev.title, specs=specs,
                 occurred_at=ev.start_at, project_id=pid, integration_id=integration_id, header=header)


# ============================================================================ documents


def process_document(ws: Workspace, doc: m.Document, integration_id: str | None,
                     chunk_specs: list[ChunkSpec] | None = None) -> None:
    db, g = ws.db, ws.graph
    if doc.status == "error":
        return
    src = ("document", doc.id)
    author = (doc.doc_metadata or {}).get("author")
    author_pid = None
    if author:
        res = ws.resolver.resolve_person(author, create=False)
        author_pid = res.person_id
    doc.author_person_id = author_pid
    when = ensure_aware(doc.authored_at) or doc.created_at or ws.now()
    if author_pid:
        g.add_edge(("person", author_pid), "CREATED", src, valid_from=when, observed_at=when, origin="structural",
                   confidence=0.8)
    people = {p for p in [author_pid] if p}
    pid, _ = associate(db, ws.user_id, subject_type="document", subject_id=doc.id, title=doc.title, body=doc.text[:20000],
                       participant_ids=people, rule_keys=[f"document:{doc.id}"])
    doc.project_id = pid
    if pid:
        g.add_edge(src, "BELONGS_TO", ("project", pid), observed_at=when, confidence=0.8)
    ctx = SourceCtx(source_type="document", source_id=doc.id, title=doc.title, text=doc.text[:50000], occurred_at=when,
                    integration_id=integration_id, speaker_pid=author_pid, participant_pids=people, project_id=pid,
                    source_kind="document")
    run_extraction(ws, ctx)
    # emails that attached this file now reference it
    for e in db.scalars(select(m.Email).where(m.Email.user_id == ws.user_id)):
        if any((a.get("filename") or "").lower() == doc.original_filename.lower() for a in (e.attachments or [])):
            g.add_edge(("email", e.id), "REFERENCES", src, observed_at=e.sent_at, origin="structural",
                       properties={"via": "attachment"})
    _timeline(ws, when, "document", f"Document: {doc.title}", None, src, pid, list(people))
    if chunk_specs is None:
        from app.documents.service import chunks_for

        chunk_specs = chunks_for(doc)
    specs = chunk_specs
    index_chunks(db, user_id=ws.user_id, owner_type="document", owner_id=doc.id, title=doc.title, specs=specs,
                 occurred_at=when, project_id=pid, integration_id=integration_id, header=f"Document: {doc.title}\n")
    doc.status = "ready"


# ============================================================================ notes


_BACKLINK = re.compile(r"\[\[([^\]]{1,120})\]\]")
_TAG = re.compile(r"(?<![\w#])#([A-Za-z][\w\-]{1,40})")
_CHECKBOX = re.compile(r"^\s*[-*]\s+\[ \]\s+(.+)$", re.MULTILINE)


def process_note(ws: Workspace, note: m.Note, integration_id: str | None) -> None:
    db, g = ws.db, ws.graph
    src = ("note", note.id)
    when = note.updated_at or note.created_at or ws.now()
    tags = sorted(set(note.tags or []) | {t.lower() for t in _TAG.findall(note.body)})
    note.tags = tags
    annotations: list[dict[str, Any]] = []
    for title in _BACKLINK.findall(note.body):
        target = db.scalar(select(m.Note).where(m.Note.user_id == ws.user_id, m.Note.title.ilike(title.strip())))
        if target and target.id != note.id:
            g.add_edge(src, "RELATED_TO", ("note", target.id), observed_at=when, origin="structural",
                       properties={"via": "backlink"})
    gaz = ws.gazetteer()
    people: set[str] = set()
    for pm in extract_people(note.body, gaz):
        res = ws.resolver.resolve_person(pm.name, create=False)
        if res.person_id:
            people.add(res.person_id)
            annotations.append({"type": "person", "text": pm.span.text if pm.span else pm.name, "ref_id": res.person_id,
                                "confidence": round(pm.confidence, 2), "origin": "ai"})
    if note.project_id is None:
        pid, inf = associate(db, ws.user_id, subject_type="note", subject_id=note.id, title=note.title, body=note.body,
                             participant_ids=people, rule_keys=[f"note:{note.id}"])
        if inf is not None:
            annotations.append({"type": "project", "text": inf.value_label, "ref_id": inf.value_id,
                                "confidence": inf.confidence, "status": inf.status, "reasons": inf.reasons, "origin": "ai"})
        if pid:
            note.project_id = pid
    if note.project_id:
        g.add_edge(src, "BELONGS_TO", ("project", note.project_id), observed_at=when, confidence=0.9)
    ctx = SourceCtx(source_type="note", source_id=note.id, title=note.title, text=note.body, occurred_at=when,
                    integration_id=integration_id, speaker_pid=ws.self_person_id, participant_pids=people,
                    project_id=note.project_id, source_kind="note")
    run_extraction(ws, ctx)
    for line in _CHECKBOX.findall(note.body):
        _suggest_task(ws, title=line.strip()[:300], source=src, span=line.strip(), confidence=0.9,
                      project_id=note.project_id, due_at=None, owner=ws.self_person_id)
        annotations.append({"type": "task", "text": line.strip()[:120], "origin": "ai", "confidence": 0.9})
    note.ai_annotations = annotations  # stored separately; the user's markdown is never modified
    note.updated_at = when  # annotating is not a user edit: keep the note's own timestamp
    index_chunks(db, user_id=ws.user_id, owner_type="note", owner_id=note.id, title=note.title,
                 specs=chunk_plain(note.body or note.title), occurred_at=when, project_id=note.project_id,
                 integration_id=integration_id, header=f"Note: {note.title}\n")


# ============================================================================ shared extraction


def rule_extract(ws: Workspace, ctx: SourceCtx) -> ExtractionResult:
    gaz = ws.gazetteer()
    names = _names(ws, [ctx.speaker_pid] if ctx.speaker_pid else [])
    ectx = ExtractionContext(sent_at=ctx.occurred_at, timezone=ws.tz, subject=ctx.title,
                             speaker_name=names[0] if names else None, source_kind=ctx.source_kind)
    return ExtractionResult(
        people=extract_people(ctx.text, gaz),
        organizations=extract_orgs(ctx.text, gaz),
        projects=extract_projects(f"{ctx.title}\n{ctx.text}", gaz),
        commitments=extract_commitments(ctx.text, ectx),
        completions=extract_completions(ctx.text, ectx),
        decisions=extract_decisions(ctx.text),
        deadline_changes=extract_deadline_changes(ctx.text, ctx.occurred_at, ws.tz),
        employment=extract_employment(ctx.text, ctx.signature, names[0] if names else None),
        blockers=extract_blockers(ctx.text),
    )


def _names(ws: Workspace, pids: list[str]) -> list[str]:
    out = []
    for pid in pids:
        p = ws.db.get(m.Person, pid)
        if p:
            out.append(p.display_name)
    return out


def run_extraction(ws: Workspace, ctx: SourceCtx) -> ExtractionResult:
    result = rule_extract(ws, ctx)
    if ws.settings.llm_extraction_enabled and ctx.text.strip():
        _merge_llm(ws, ctx, result)
    persist_extraction(ws, ctx, result)
    return result


def _merge_llm(ws: Workspace, ctx: SourceCtx, result: ExtractionResult) -> None:
    from app.ai.llm.base import LLMError
    from app.ai.llm.gateway import LLMGateway
    from app.ai.structured import StructuredOutputError
    from app.core.errors import PrivacyViolation
    from app.extraction.llm_extractor import llm_extract

    try:
        payload = llm_extract(LLMGateway(ws.db, ws.user_id), text=ctx.text, sent_at=ctx.occurred_at, tz=ws.tz,
                              speaker=next(iter(_names(ws, [ctx.speaker_pid])), None) if ctx.speaker_pid else None,
                              addressees=_names(ws, ctx.addressee_pids), integration_id=ctx.integration_id)
    except (LLMError, StructuredOutputError, PrivacyViolation) as exc:
        # Rules already ran, so the item is still processed; the failure is recorded, not swallowed.
        ws.db.add(m.AuditLog(user_id=ws.user_id, actor="system", action="llm_extraction_failed",
                             target_type=ctx.source_type, target_id=ctx.source_id,
                             details={"error": f"{type(exc).__name__}: {str(exc)[:200]}"}))
        log.warning("llm_extraction_failed", source_id=ctx.source_id, error=type(exc).__name__)
        return
    covered = [(c.span_start or -1, c.span_end or -1) for c in result.commitments]
    for c in payload.commitments:
        if any(a <= (c.span_start or 0) < b for a, b in covered):
            continue
        c.confidence = min(c.confidence, 0.8)
        result.commitments.append(c)
    dcovered = [(d.span_start or -1, d.span_end or -1) for d in result.decisions]
    for d in payload.decisions:
        if not any(a <= (d.span_start or 0) < b for a, b in dcovered):
            result.decisions.append(d)
    result.extractor = "rules+llm"


def persist_extraction(ws: Workspace, ctx: SourceCtx, result: ExtractionResult) -> None:
    db, g = ws.db, ws.graph
    src = (ctx.source_type, ctx.source_id)
    # mentioned people / orgs / projects
    for pm in result.people:
        res = ws.resolver.resolve_person(pm.name, context_ids=ctx.participant_pids, create=False)
        if res.person_id:
            g.add_edge(src, "MENTIONS", ("person", res.person_id), observed_at=ctx.occurred_at,
                       confidence=pm.confidence, source=src, span=pm.span.text if pm.span else None)
    for om in result.organizations:
        org = ws.resolver.resolve_org(om.name)
        if org:
            g.add_edge(src, "MENTIONS", ("organization", org.id), observed_at=ctx.occurred_at, confidence=om.confidence,
                       source=src, span=om.span.text if om.span else None)
    for prm in result.projects:
        proj = db.scalar(select(m.Project).where(m.Project.user_id == ws.user_id, m.Project.name.ilike(prm.name)))
        if proj:
            g.add_edge(src, "MENTIONS", ("project", proj.id), observed_at=ctx.occurred_at, confidence=prm.confidence,
                       source=src, span=prm.span.text if prm.span else None)

    created: list[m.Commitment | None] = []
    for c in result.commitments:
        created.append(_persist_commitment(ws, ctx, c))
    for i, c in enumerate(result.commitments):
        if c.depends_on_index is not None and 0 <= c.depends_on_index < len(created):
            a, b = created[i], created[c.depends_on_index]
            if a and b:
                g.add_edge(("commitment", a.id), "DEPENDS_ON", ("commitment", b.id), observed_at=ctx.occurred_at,
                           source=src, span=c.source_span, confidence=0.8)
    for d in result.decisions:
        _persist_decision(ws, ctx, d)
    for dc in result.deadline_changes:
        _apply_deadline_change(ws, ctx, dc)
    for ef in result.employment:
        _apply_employment(ws, ctx, ef)
    for blk in result.blockers:
        _apply_blocker(ws, ctx, blk)


def _actor_pid(ws: Workspace, ctx: SourceCtx, actor: str) -> tuple[str | None, float]:
    if actor == SPEAKER:
        return ctx.speaker_pid, 0.0
    if actor == ADDRESSEE:
        if not ctx.addressee_pids:
            return None, -0.2
        return ctx.addressee_pids[0], (0.0 if len(ctx.addressee_pids) == 1 else -0.08)
    res = ws.resolver.resolve_person(actor, context_ids=ctx.participant_pids, create=len(actor.split()) >= 2)
    return res.person_id, (0.0 if res.person_id else -0.15)


def _person_name(ws: Workspace, pid: str | None, fallback: str | None = None) -> str:
    if pid == ws.self_person_id and pid:
        return "You"
    p = ws.db.get(m.Person, pid) if pid else None
    return p.display_name if p else (fallback or "Someone")


def _persist_commitment(ws: Workspace, ctx: SourceCtx, c: CommitmentExtraction) -> m.Commitment | None:
    db, g = ws.db, ws.graph
    actor_pid, penalty = _actor_pid(ws, ctx, c.actor)
    recipient_pid = None
    if c.recipient:
        recipient_pid, _ = _actor_pid(ws, ctx, c.recipient)
    if actor_pid and recipient_pid == actor_pid:
        recipient_pid = None
    key = stable_hash(ws.user_id, ctx.source_id, c.span_start, c.action, c.actor, (c.object or "")[:60])
    existing = db.scalar(select(m.Commitment).where(m.Commitment.user_id == ws.user_id, m.Commitment.dedupe_key == key))
    actor_name = _person_name(ws, actor_pid, None if c.actor in (SPEAKER, ADDRESSEE) else c.actor)
    verb = "will" if c.kind == "commitment" else ("asked to" if c.kind == "request" else "might")
    desc = f"{actor_name} {verb} {c.action} {c.object or ''}".strip()
    if c.kind == "request":
        requester = _person_name(ws, recipient_pid) if recipient_pid else "Someone"
        asked = "you" if actor_pid and actor_pid == ws.self_person_id else actor_name
        desc = f"{requester} asked {asked} to {c.action} {c.object or ''}".strip()
    if existing and (existing.user_modified or existing.user_confirmed):
        return existing
    if existing is None and actor_pid and c.kind != "intention":
        same = _find_restated_commitment(ws, actor_pid, c, ctx.occurred_at)
        if same is not None:
            # Consolidation: the same promise restated elsewhere (meeting notes, then email) reinforces the
            # existing commitment with extra evidence instead of creating a duplicate memory.
            db.add(m.Evidence(user_id=ws.user_id, subject_type="commitment", subject_id=same.id, source_type=ctx.source_type,
                              source_id=ctx.source_id, location={"char_start": c.span_start, "char_end": c.span_end},
                              span=c.source_span, observed_at=ctx.occurred_at, confidence=c.confidence, role="reaffirmed"))
            if c.due_at and (same.due_at is None or not _has_due_change(db, same.id)):
                same.due_at, same.due_text = same.due_at or c.due_at, same.due_text or c.due_text
            same.confidence = round(min(0.97, max(same.confidence, c.confidence) + 0.03), 3)
            ws.graph.add_edge(("commitment", same.id), "EXTRACTED_FROM", (ctx.source_type, ctx.source_id),
                              observed_at=ctx.occurred_at, origin="structural", properties={"role": "reaffirmed"})
            return same
    status = "UNCERTAIN" if c.kind == "intention" else "OPEN"
    conf = round(max(0.05, c.confidence + penalty), 3)
    if existing:
        row = existing
        row.action, row.object, row.description, row.confidence = c.action, c.object, desc, conf
        row.actor_person_id, row.recipient_person_id = actor_pid, recipient_pid
        row.due_at = row.due_at if row.due_at and row.due_at != c.due_at and _has_due_change(db, row.id) else c.due_at
    else:
        row = m.Commitment(
            user_id=ws.user_id, kind=c.kind, actor_person_id=actor_pid, recipient_person_id=recipient_pid,
            actor_text=c.actor if c.actor not in (SPEAKER, ADDRESSEE) else None, action=c.action, object=c.object,
            description=desc, source_type=ctx.source_type, source_id=ctx.source_id, evidence_span=c.source_span,
            span_start=c.span_start, span_end=c.span_end, detected_at=ctx.occurred_at, due_at=c.due_at,
            due_text=c.due_text, status=status, confidence=conf, extractor="llm" if c.span_start is None else "rules",
            project_id=ctx.project_id, dedupe_key=key,
        )
        db.add(row)
        db.flush()
        db.add(m.Evidence(user_id=ws.user_id, subject_type="commitment", subject_id=row.id, source_type=ctx.source_type,
                          source_id=ctx.source_id, location={"char_start": c.span_start, "char_end": c.span_end},
                          span=c.source_span, observed_at=ctx.occurred_at, confidence=conf))
        _timeline(ws, ctx.occurred_at, "commitment", desc, c.source_span, ("commitment", row.id), ctx.project_id,
                  [p for p in [actor_pid, recipient_pid] if p])
    src = (ctx.source_type, ctx.source_id)
    if actor_pid:
        rel = "COMMITTED_TO" if c.kind != "request" else "ASSIGNED_TO"
        if rel == "COMMITTED_TO":
            g.add_edge(("person", actor_pid), rel, ("commitment", row.id), valid_from=ctx.occurred_at,
                       observed_at=ctx.occurred_at, confidence=conf, source=src, span=c.source_span,
                       properties={"due": c.due_at.isoformat() if c.due_at else None})
        else:
            g.add_edge(("commitment", row.id), rel, ("person", actor_pid), valid_from=ctx.occurred_at,
                       observed_at=ctx.occurred_at, confidence=conf, source=src, span=c.source_span)
    if recipient_pid:
        g.add_edge(("commitment", row.id), "FOR", ("person", recipient_pid), observed_at=ctx.occurred_at,
                   confidence=conf, source=src)
    g.add_edge(("commitment", row.id), "EXTRACTED_FROM", src, observed_at=ctx.occurred_at, origin="structural")
    if ctx.project_id:
        row.project_id = row.project_id or ctx.project_id
        g.add_edge(("commitment", row.id), "BELONGS_TO", ("project", ctx.project_id), observed_at=ctx.occurred_at,
                   confidence=0.8)
    if actor_pid and actor_pid == ws.self_person_id and c.kind in ("commitment", "request"):
        _suggest_task(ws, title=f"{c.action.capitalize()} {c.object or ''}".strip(), source=src, span=c.source_span,
                      confidence=conf, project_id=ctx.project_id, due_at=c.due_at, owner=actor_pid,
                      key_extra=row.dedupe_key)
    return row


def _find_restated_commitment(ws: Workspace, actor_pid: str, c: CommitmentExtraction, at: datetime) -> m.Commitment | None:
    """Same actor, near-identical object, compatible due date, stated within 30 days."""

    words = content_words(c.object or "") - {"document", "doc", "new", "updat", "final", "first"}
    if not words:
        return None
    for prior in ws.db.scalars(select(m.Commitment).where(
            m.Commitment.user_id == ws.user_id, m.Commitment.actor_person_id == actor_pid, m.Commitment.kind == c.kind,
            m.Commitment.status.in_(["OPEN", "OVERDUE", "UNCERTAIN", "FULFILLED"]))):
        det = ensure_aware(prior.detected_at)
        if det is None or abs((at - det).total_seconds()) > 30 * 86400:
            continue
        pw = content_words(prior.object or "") - {"document", "doc", "new", "updat", "final", "first"}
        if not pw or len(words & pw) / len(words | pw) < 0.6:
            continue
        pd, cd = ensure_aware(prior.due_at), c.due_at
        if pd and cd and abs((pd - cd).total_seconds()) > 86400:
            continue  # same object, different deadline: a new promise (e.g. "update the doc by Sep 30")
        if prior.status == "FULFILLED" and prior.resolved_at and ensure_aware(prior.resolved_at) < at:  # type: ignore[operator]
            continue  # already delivered before this statement: this is a new promise
        return prior
    return None


def _has_due_change(db: Session, commitment_id: str) -> bool:
    return db.scalar(select(m.CommitmentDueChange.id).where(m.CommitmentDueChange.commitment_id == commitment_id).limit(1)) is not None


def _suggest_task(ws: Workspace, *, title: str, source: tuple[str, str], span: str, confidence: float,
                  project_id: str | None, due_at: datetime | None, owner: str | None, key_extra: str = "") -> m.Task:
    """AI-detected actions become *suggestions*. Only the user (or an explicit auto-create setting) activates them."""
    key = stable_hash(ws.user_id, "task", source[1], key_extra or title.lower())
    t = ws.db.scalar(select(m.Task).where(m.Task.user_id == ws.user_id, m.Task.dedupe_key == key))
    if t:
        return t
    t = m.Task(user_id=ws.user_id, title=title[:500], project_id=project_id, owner_person_id=owner,
               status="active" if ws.settings.auto_create_tasks and confidence >= AUTO_TASK_MIN_CONFIDENCE else "suggested",
               priority="medium", due_at=due_at,
               source_type=source[0], source_id=source[1], evidence_span=span, confidence=confidence,
               ai_suggested=True, manually_created=False, dedupe_key=key)
    ws.db.add(t)
    ws.db.flush()
    ws.graph.add_edge(("task", t.id), "EXTRACTED_FROM", source, observed_at=ws.now(), origin="structural")
    if project_id:
        ws.graph.add_edge(("task", t.id), "BELONGS_TO", ("project", project_id), observed_at=ws.now(), confidence=0.8)
    if owner:
        ws.graph.add_edge(("task", t.id), "ASSIGNED_TO", ("person", owner), observed_at=ws.now(), confidence=confidence)
    return t


def _persist_decision(ws: Workspace, ctx: SourceCtx, d: DecisionExtraction) -> m.Decision:
    db, g = ws.db, ws.graph
    key = stable_hash(ws.user_id, "decision", ctx.source_id, d.span_start, d.chosen.lower())
    row = db.scalar(select(m.Decision).where(m.Decision.user_id == ws.user_id, m.Decision.dedupe_key == key))
    participants = sorted(p for p in ({ctx.speaker_pid} | set(ctx.addressee_pids) | ctx.participant_pids) if p)
    if row is None:
        # A restatement of the same choice (same project + topic + chosen, within 14 days, or a later
        # document repeating an earlier decision) reinforces the existing decision instead of duplicating it.
        same = db.scalars(select(m.Decision).where(
            m.Decision.user_id == ws.user_id, m.Decision.topic == d.topic, m.Decision.chosen.ilike(d.chosen),
            (m.Decision.project_id == ctx.project_id) if ctx.project_id else m.Decision.project_id.is_(None)))
        for prior in same:
            gap = abs((ensure_aware(prior.decided_at) - ctx.occurred_at).total_seconds()) / 86400  # type: ignore[operator]
            if gap <= 14 or ctx.source_type == "document" or prior.source_type == "document":
                db.add(m.Evidence(user_id=ws.user_id, subject_type="decision", subject_id=prior.id,
                                  source_type=ctx.source_type, source_id=ctx.source_id, span=d.source_span,
                                  observed_at=ctx.occurred_at, confidence=d.confidence, role="reaffirmed",
                                  location={"char_start": d.span_start, "char_end": d.span_end}))
                if ctx.occurred_at < ensure_aware(prior.decided_at):  # type: ignore[operator]
                    # the earliest statement dates the decision and becomes its primary source
                    prior.decided_at = ctx.occurred_at
                    prior.source_type, prior.source_id = ctx.source_type, ctx.source_id
                    prior.statement = prior.evidence_span = d.source_span
                    for te in db.scalars(select(m.TimelineEvent).where(m.TimelineEvent.ref_id == prior.id)):
                        te.occurred_at, te.detail = ctx.occurred_at, d.source_span
                    _supersede_decisions(ws, prior)
                ws.graph.add_edge(("decision", prior.id), "DECIDED_IN", (ctx.source_type, ctx.source_id),
                                  observed_at=ctx.occurred_at, source=(ctx.source_type, ctx.source_id),
                                  span=d.source_span, confidence=d.confidence)
                subj = ("project", ctx.project_id) if ctx.project_id else ("topic", _topic(ws, d.topic).id)
                ws.memory.record_fact(subject=subj, attribute=f"decision:{d.topic}", value=prior.chosen,
                                      content=f"Decided {prior.chosen} ({d.topic})", valid_from=ctx.occurred_at,
                                      observed_at=ctx.occurred_at, source=(ctx.source_type, ctx.source_id),
                                      span=d.source_span, confidence=d.confidence)
                return prior
    if row is None:
        row = m.Decision(user_id=ws.user_id, topic=d.topic, chosen=d.chosen, rejected=d.rejected, statement=d.source_span,
                         decided_at=ctx.occurred_at, project_id=ctx.project_id, source_type=ctx.source_type,
                         source_id=ctx.source_id, evidence_span=d.source_span, confidence=d.confidence,
                         participants=participants, dedupe_key=key)
        db.add(row)
        db.flush()
        db.add(m.Evidence(user_id=ws.user_id, subject_type="decision", subject_id=row.id, source_type=ctx.source_type,
                          source_id=ctx.source_id, location={"char_start": d.span_start, "char_end": d.span_end},
                          span=d.source_span, observed_at=ctx.occurred_at, confidence=d.confidence))
    src = (ctx.source_type, ctx.source_id)
    g.add_edge(("decision", row.id), "DECIDED_IN", src, valid_from=ctx.occurred_at, observed_at=ctx.occurred_at,
               source=src, span=d.source_span, confidence=d.confidence)
    topic = _topic(ws, d.topic)
    g.add_edge(("decision", row.id), "ABOUT", ("topic", topic.id), observed_at=ctx.occurred_at, origin="structural")
    if ctx.project_id:
        g.add_edge(("decision", row.id), "BELONGS_TO", ("project", ctx.project_id), observed_at=ctx.occurred_at)
    for pid in participants:
        g.add_edge(("person", pid), "PARTICIPATES_IN", ("decision", row.id), observed_at=ctx.occurred_at,
                   origin="structural", confidence=0.7)
    _supersede_decisions(ws, row)
    subject = ("project", ctx.project_id) if ctx.project_id else ("topic", topic.id)
    ws.memory.record_fact(subject=subject, attribute=f"decision:{d.topic}", value=d.chosen,
                          content=f"Decided {d.chosen}" + (f" over {', '.join(d.rejected)}" if d.rejected else "") + f" ({d.topic})",
                          valid_from=ctx.occurred_at, observed_at=ctx.occurred_at, source=src, span=d.source_span,
                          confidence=d.confidence)
    _timeline(ws, ctx.occurred_at, "decision", f"Decision ({d.topic}): {d.chosen}", d.source_span, ("decision", row.id),
              ctx.project_id, participants)
    ws.memory.record_episode(content=f"Decision on {d.topic}: {d.chosen}", occurred_at=ctx.occurred_at, subject=subject,
                             source=src, span=d.source_span)
    return row


def _supersede_decisions(ws: Workspace, new: m.Decision) -> None:
    """Order decisions on the same (project, topic) by time; each is superseded by the next one."""
    same = list(ws.db.scalars(select(m.Decision).where(
        m.Decision.user_id == ws.user_id, m.Decision.topic == new.topic, m.Decision.status != "rejected",
        (m.Decision.project_id == new.project_id) if new.project_id else m.Decision.project_id.is_(None))))
    same.sort(key=lambda d: ensure_aware(d.decided_at))  # type: ignore[arg-type, return-value]
    for i, d in enumerate(same):
        nxt = next((x for x in same[i + 1:] if x.chosen.lower() != d.chosen.lower()), None)
        if nxt is not None:
            if d.superseded_by_id != nxt.id:
                d.status, d.superseded_by_id = "superseded", nxt.id
                ws.graph.add_edge(("decision", nxt.id), "SUPERSEDES", ("decision", d.id), valid_from=nxt.decided_at,
                                  observed_at=nxt.decided_at, origin="structural",
                                  source=(nxt.source_type, nxt.source_id), span=nxt.statement)
        elif not d.user_confirmed or d.status != "rejected":
            d.status, d.superseded_by_id = "active", None


def _apply_deadline_change(ws: Workspace, ctx: SourceCtx, dc: Any) -> None:
    db = ws.db
    src = (ctx.source_type, ctx.source_id)
    words = content_words(dc.subject) - {"deadline", "date", "due"}
    if ctx.project_id:
        proj = db.get(m.Project, ctx.project_id)
        key_words = words - (content_words(proj.name) if proj else set()) - {"project"}
        attr = "deadline:" + (" ".join(sorted(re.sub(r"[^a-z ]", "", w) for w in key_words)) or "project")
        ws.memory.record_fact(subject=("project", ctx.project_id), attribute=attr, value=dc.new_due_at.date().isoformat(),
                              content=f"{dc.subject.capitalize()} due {dc.new_due_at.date().isoformat()}",
                              valid_from=ctx.occurred_at, observed_at=ctx.occurred_at, source=src, span=dc.source_span,
                              confidence=dc.confidence)
        if dc.kind == "moved":
            _timeline(ws, ctx.occurred_at, "deadline_change", f"{dc.subject.capitalize()} moved to {dc.new_due_at.date().isoformat()}",
                      dc.source_span, src, ctx.project_id, [])
    if dc.kind != "moved":
        return
    # Move matching open commitments in the same thread or project.
    q = select(m.Commitment).where(m.Commitment.user_id == ws.user_id, m.Commitment.status.in_(["OPEN", "OVERDUE", "UNCERTAIN"]),
                                   m.Commitment.detected_at <= ctx.occurred_at)
    candidates = list(db.scalars(q))
    for c in candidates:
        same_scope = (ctx.project_id and c.project_id == ctx.project_id) or (
            ctx.thread_id and c.source_type == "email" and _thread_of(db, c.source_id) == ctx.thread_id)
        if not same_scope or c.user_modified:
            continue
        overlap = words & content_words(f"{c.object or ''} {c.description}")
        if not overlap and words:
            continue
        if db.scalar(select(m.CommitmentDueChange.id).where(m.CommitmentDueChange.commitment_id == c.id,
                                                            m.CommitmentDueChange.source_id == ctx.source_id)):
            continue
        db.add(m.CommitmentDueChange(user_id=ws.user_id, commitment_id=c.id, old_due_at=c.due_at, new_due_at=dc.new_due_at,
                                     source_type=ctx.source_type, source_id=ctx.source_id, evidence_span=dc.source_span,
                                     observed_at=ctx.occurred_at))
        db.add(m.Evidence(user_id=ws.user_id, subject_type="commitment", subject_id=c.id, source_type=ctx.source_type,
                          source_id=ctx.source_id, span=dc.source_span, observed_at=ctx.occurred_at, role="change",
                          confidence=dc.confidence))
        c.due_at, c.due_text = dc.new_due_at, dc.due_text
        if c.status == "OVERDUE" and dc.new_due_at > ws.now():
            c.status = "OPEN"


def _thread_of(db: Session, email_id: str) -> str | None:
    e = db.get(m.Email, email_id)
    return e.thread_id if e else None


def _apply_employment(ws: Workspace, ctx: SourceCtx, ef: Any) -> None:
    src = (ctx.source_type, ctx.source_id)
    res = ws.resolver.resolve_person(ef.person, context_ids=ctx.participant_pids, create=False)
    if not res.person_id:
        return
    org = ws.resolver.resolve_org(ef.organization)
    if not org:
        return
    if ef.kind == "left":
        for e in ws.db.scalars(select(m.Relationship).where(
                m.Relationship.user_id == ws.user_id, m.Relationship.src_id == res.person_id,
                m.Relationship.rel_type == "WORKS_AT", m.Relationship.dst_id == org.id, m.Relationship.status == "active")):
            e.valid_to, e.status = ctx.occurred_at, "superseded"
    else:
        ws.graph.add_edge(("person", res.person_id), "WORKS_AT", ("organization", org.id), valid_from=ctx.occurred_at,
                          observed_at=ctx.occurred_at, confidence=ef.confidence, source=src, span=ef.source_span,
                          properties={"title": ef.title} if ef.title else {})
        p = ws.db.get(m.Person, res.person_id)
        if p and ef.title:
            p.title = ef.title
    ws.memory.record_fact(subject=("person", res.person_id), attribute="works_at", value=org.name if ef.kind != "left" else f"(left {org.name})",
                          content=f"{ef.person} {'works at' if ef.kind != 'left' else 'left'} {org.name}", valid_from=ctx.occurred_at,
                          observed_at=ctx.occurred_at, source=src, span=ef.source_span, confidence=ef.confidence)
    if ef.kind == "joined":
        _timeline(ws, ctx.occurred_at, "employment", f"{ef.person} joined {org.name}", ef.source_span, src, None, [res.person_id])
    _refresh_current_org(ws, res.person_id)


def _apply_blocker(ws: Workspace, ctx: SourceCtx, b: Any) -> None:
    src = (ctx.source_type, ctx.source_id)
    res = ws.resolver.resolve_person(b.blocked_by, context_ids=ctx.participant_pids, create=False)
    words = content_words(b.blocked_item)
    matched = False
    for t in ws.db.scalars(select(m.Task).where(m.Task.user_id == ws.user_id, m.Task.status.in_(["active", "suggested", "blocked"]))):
        overlap = words & content_words(t.title)
        if words and len(overlap) / len(words) >= 0.6 and not t.user_modified:
            t.status = "blocked" if t.status != "suggested" else t.status
            t.blocked_by_person_id = res.person_id
            t.blocked_reason = b.source_span
            if res.person_id:
                ws.graph.add_edge(("task", t.id), "BLOCKED_BY", ("person", res.person_id), observed_at=ctx.occurred_at,
                                  source=src, span=b.source_span, confidence=0.75)
            matched = True
    if not matched:
        node = ("project", ctx.project_id) if ctx.project_id else src
        target = ("person", res.person_id) if res.person_id else ("topic", _topic(ws, b.blocked_by.lower()).id)
        ws.graph.add_edge(node, "BLOCKED_BY", target, observed_at=ctx.occurred_at, source=src, span=b.source_span,
                          confidence=0.7, properties={"item": b.blocked_item})


def _topic(ws: Workspace, name: str) -> m.Topic:
    name = name.strip().lower()[:200]
    t = ws.db.scalar(select(m.Topic).where(m.Topic.user_id == ws.user_id, m.Topic.name == name))
    if t is None:
        t = m.Topic(user_id=ws.user_id, name=name)
        ws.db.add(t)
        ws.db.flush()
    return t


def _timeline(ws: Workspace, at: datetime, kind: str, title: str, detail: str | None, ref: tuple[str, str],
              project_id: str | None, person_ids: list[str]) -> None:
    key = stable_hash(ws.user_id, "timeline", kind, ref[0], ref[1], title[:120])
    if ws.db.scalar(select(m.TimelineEvent.id).where(m.TimelineEvent.user_id == ws.user_id, m.TimelineEvent.dedupe_key == key)):
        return
    ws.db.add(m.TimelineEvent(user_id=ws.user_id, occurred_at=at, kind=kind, title=title[:500], detail=detail,
                              ref_type=ref[0], ref_id=ref[1], project_id=project_id, person_ids=person_ids, dedupe_key=key))
