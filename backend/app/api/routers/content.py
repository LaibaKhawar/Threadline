"""Emails/threads, calendar (+ meeting briefs), documents (upload/download) and notes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.api.deps import rate_limit, workspace
from app.api.serialize import commitment_dict, decision_dict, document_dict, email_dict, event_dict, iso, note_dict, project_brief
from app.core.config import get_settings
from app.db import models as m
from app.documents.validation import UploadRejected, storage_path
from app.domain.events import SOURCE_ITEM_DELETED, SOURCE_ITEM_UPSERTED, dispatch, publish
from app.extraction.text import stable_hash
from app.ingestion.workspace import Workspace
from app.intelligence.briefs import meeting_brief
from app.services.accounts import internal_integration

router = APIRouter(prefix="/api", tags=["content"])


# ------------------------------------------------------------------------------------- email


@router.get("/threads")
def threads(project_id: str | None = None, awaiting: str | None = None, q: str | None = None, limit: int = Query(100, le=500),
            ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    db = ws.db
    query = select(m.EmailThread).where(m.EmailThread.user_id == ws.user_id, m.EmailThread.first_at <= ws.now())
    if project_id:
        query = query.where(m.EmailThread.project_id == project_id)
    if awaiting:
        query = query.where(m.EmailThread.awaiting == awaiting)
    if q:
        query = query.where(m.EmailThread.subject.ilike(f"%{q}%"))
    rows = list(db.scalars(query.order_by(m.EmailThread.last_at.desc()).limit(limit)))
    out = []
    for t in rows:
        last = db.scalar(select(m.Email).where(m.Email.thread_id == t.id).order_by(m.Email.sent_at.desc()).limit(1))
        ids = list(db.scalars(select(m.Email.id).where(m.Email.thread_id == t.id)))
        n_commit = db.scalar(select(func.count()).select_from(m.Commitment).where(m.Commitment.source_id.in_(ids))) if ids else 0
        out.append({"id": t.id, "subject": t.subject, "message_count": t.message_count, "first_at": iso(t.first_at), "last_at": iso(t.last_at),
                    "project": project_brief(db, t.project_id), "awaiting": t.awaiting, "commitments": n_commit,
                    "last": email_dict(db, last) if last else None, "importance": max([last.importance if last else 0.0])})
    return {"items": out}


@router.get("/threads/{tid}")
def thread(tid: str, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    db = ws.db
    t = db.get(m.EmailThread, tid)
    if not t or t.user_id != ws.user_id:
        raise HTTPException(404, "not found")
    emails = list(db.scalars(select(m.Email).where(m.Email.thread_id == tid).order_by(m.Email.sent_at)))
    ids = [e.id for e in emails]
    commitments = list(db.scalars(select(m.Commitment).where(m.Commitment.source_id.in_(ids))))
    decisions = list(db.scalars(select(m.Decision).where(m.Decision.source_id.in_(ids))))
    tasks = list(db.scalars(select(m.Task).where(m.Task.source_id.in_(ids))))
    infs = list(db.scalars(select(m.Inference).where(m.Inference.subject_id.in_(ids), m.Inference.kind == "project_association")))
    from app.api.serialize import task_dict

    return {"id": t.id, "subject": t.subject, "project": project_brief(db, t.project_id), "awaiting": t.awaiting,
            "emails": [email_dict(db, e, full=True) for e in emails],
            "commitments": [commitment_dict(db, c) for c in commitments], "decisions": [decision_dict(db, d) for d in decisions],
            "tasks": [task_dict(db, x) for x in tasks],
            "inferences": [{"id": i.id, "subject_id": i.subject_id, "value_label": i.value_label, "value_id": i.value_id,
                            "confidence": i.confidence, "reasons": i.reasons, "status": i.status} for i in infs]}


@router.get("/emails/{eid}")
def email(eid: str, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    e = ws.db.get(m.Email, eid)
    if not e or e.user_id != ws.user_id:
        raise HTTPException(404, "not found")
    d = email_dict(ws.db, e, full=True)
    d["commitments"] = [commitment_dict(ws.db, c) for c in ws.db.scalars(select(m.Commitment).where(m.Commitment.source_id == eid))]
    d["decisions"] = [decision_dict(ws.db, x) for x in ws.db.scalars(select(m.Decision).where(m.Decision.source_id == eid))]
    return d


# ------------------------------------------------------------------------------------- calendar


@router.get("/events")
def events(start: datetime | None = None, end: datetime | None = None, project_id: str | None = None,
           ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    q = select(m.CalendarEvent).where(m.CalendarEvent.user_id == ws.user_id)
    if start:
        q = q.where(m.CalendarEvent.start_at >= start)
    if end:
        q = q.where(m.CalendarEvent.start_at <= end)
    if project_id:
        q = q.where(m.CalendarEvent.project_id == project_id)
    rows = list(ws.db.scalars(q.order_by(m.CalendarEvent.start_at.desc()).limit(500)))
    return {"now": ws.now().isoformat(), "items": [event_dict(ws.db, e) for e in rows]}


@router.get("/events/{eid}")
def event(eid: str, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    e = ws.db.get(m.CalendarEvent, eid)
    if not e or e.user_id != ws.user_id:
        raise HTTPException(404, "not found")
    d = event_dict(ws.db, e)
    d["commitments"] = [commitment_dict(ws.db, c) for c in ws.db.scalars(select(m.Commitment).where(m.Commitment.source_id == eid))]
    d["decisions"] = [decision_dict(ws.db, x) for x in ws.db.scalars(select(m.Decision).where(m.Decision.source_id == eid))]
    return d


@router.get("/events/{eid}/brief")
def brief(eid: str, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    try:
        return meeting_brief(ws, eid)
    except LookupError as exc:
        raise HTTPException(404, "not found") from exc


# ------------------------------------------------------------------------------------- documents


@router.get("/documents")
def documents(project_id: str | None = None, q: str | None = None, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    query = select(m.Document).where(m.Document.user_id == ws.user_id)
    if project_id:
        query = query.where(m.Document.project_id == project_id)
    if q:
        query = query.where(or_(m.Document.title.ilike(f"%{q}%"), m.Document.original_filename.ilike(f"%{q}%")))
    rows = list(ws.db.scalars(query.order_by(m.Document.created_at.desc()).limit(500)))
    return {"items": [document_dict(ws.db, d) for d in rows]}


@router.get("/documents/{did}")
def document(did: str, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    d = ws.db.get(m.Document, did)
    if not d or d.user_id != ws.user_id:
        raise HTTPException(404, "not found")
    out = document_dict(ws.db, d, full=True)
    out["chunks"] = [{"id": c.id, "ordinal": c.ordinal, "page": c.page, "section": c.section, "text": c.text}
                     for c in ws.db.scalars(select(m.Chunk).where(m.Chunk.owner_type == "document", m.Chunk.owner_id == did).order_by(m.Chunk.ordinal))]
    out["decisions"] = [decision_dict(ws.db, x) for x in ws.db.scalars(select(m.Decision).where(m.Decision.source_id == did))]
    out["commitments"] = [commitment_dict(ws.db, c) for c in ws.db.scalars(select(m.Commitment).where(m.Commitment.source_id == did))]
    return out


@router.post("/documents", dependencies=[Depends(rate_limit("upload", 30))])
async def upload(file: UploadFile = File(...), ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    s = get_settings()
    user = ws.db.get(m.User, ws.user_id)
    if user is not None and user.is_demo:
        raise HTTPException(403, "uploads are disabled in the shared demo workspace; create your own account to upload files")
    limit = s.max_upload_mb * 1024 * 1024
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(413, f"file exceeds the {s.max_upload_mb} MB limit")
    integ = internal_integration(ws.db, ws.user_id, "uploads")
    import hashlib

    from app.documents.service import store_document_bytes
    from app.documents.validation import sanitize_filename

    try:
        safe_name = sanitize_filename(file.filename or "upload")
    except UploadRejected as exc:
        raise HTTPException(400, str(exc)) from exc
    ext_id = stable_hash(ws.user_id, "upload", safe_name, hashlib.sha256(content).hexdigest())
    si = ws.db.scalar(select(m.SourceItem).where(m.SourceItem.integration_id == integ.id, m.SourceItem.external_id == ext_id))
    if si is not None and si.deleted_at is None:
        existing = ws.db.scalar(select(m.Document).where(m.Document.source_item_id == si.id))
        return {"document": document_dict(ws.db, existing) if existing else None, "duplicate": True}
    if si is None:
        si = m.SourceItem(user_id=ws.user_id, integration_id=integ.id, external_id=ext_id, kind="document", content_hash=ext_id)
        ws.db.add(si)
    else:  # previously deleted: revive the same source item (identity stays deterministic)
        si.deleted_at, si.processing_status, si.processing_error = None, "pending", None
    ws.db.flush()
    try:
        doc = store_document_bytes(ws.db, ws.user_id, si, file.filename or "upload", content, declared_mime=file.content_type)
    except UploadRejected as exc:
        ws.db.rollback()
        raise HTTPException(400, str(exc)) from exc
    publish(ws.db, ws.user_id, SOURCE_ITEM_UPSERTED, {"source_item_id": si.id, "kind": "document"})
    ws.db.add(m.AuditLog(user_id=ws.user_id, actor="user", action="document_uploaded", target_type="document", target_id=doc.id,
                         details={"filename": doc.original_filename, "size": doc.size_bytes}))
    ws.db.commit()
    dispatch(ws.db, ws.user_id)
    ws.db.refresh(doc)
    return {"document": document_dict(ws.db, doc), "duplicate": False}


@router.get("/documents/{did}/download")
def download(did: str, ws: Workspace = Depends(workspace)) -> FileResponse:
    d = ws.db.get(m.Document, did)
    if not d or d.user_id != ws.user_id:
        raise HTTPException(404, "not found")
    path = storage_path(get_settings().data_dir, d.user_id, d.storage_name)
    if not path.exists():
        raise HTTPException(404, "file missing")
    return FileResponse(path, media_type=d.mime_type, filename=d.original_filename,
                        headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"})


@router.delete("/documents/{did}")
def delete_document(did: str, ws: Workspace = Depends(workspace)) -> dict[str, bool]:
    d = ws.db.get(m.Document, did)
    if not d or d.user_id != ws.user_id:
        raise HTTPException(404, "not found")
    from app.documents.service import delete_file
    from app.ingestion.purge import purge_content

    delete_file(d)
    si = ws.db.get(m.SourceItem, d.source_item_id) if d.source_item_id else None
    purge_content(ws.db, ws.user_id, "document", d.id)
    if si:
        si.deleted_at = ws.now()
    ws.db.add(m.AuditLog(user_id=ws.user_id, actor="user", action="document_deleted", target_type="document", target_id=did))
    ws.db.commit()
    return {"ok": True}


# ------------------------------------------------------------------------------------- notes


class NoteIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(default="", max_length=200_000)
    tags: list[str] = Field(default_factory=list)
    project_id: str | None = None
    pinned: bool = False


@router.get("/notes")
def notes(q: str | None = None, tag: str | None = None, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    query = select(m.Note).where(m.Note.user_id == ws.user_id)
    if q:
        query = query.where(or_(m.Note.title.ilike(f"%{q}%"), m.Note.body.ilike(f"%{q}%")))
    rows = [n for n in ws.db.scalars(query.order_by(m.Note.pinned.desc(), m.Note.updated_at.desc()).limit(500))
            if not tag or tag in (n.tags or [])]
    return {"items": [note_dict(ws.db, n) for n in rows]}


@router.get("/notes/{nid}")
def note(nid: str, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    n = ws.db.get(m.Note, nid)
    if not n or n.user_id != ws.user_id:
        raise HTTPException(404, "not found")
    d = note_dict(ws.db, n)
    # backlinks: notes that link here
    d["backlinks"] = [{"id": r.src_id, "title": (src.title if (src := ws.db.get(m.Note, r.src_id)) else "")}
                      for r in ws.db.scalars(select(m.Relationship).where(m.Relationship.user_id == ws.user_id, m.Relationship.dst_id == nid,
                                                                         m.Relationship.rel_type == "RELATED_TO", m.Relationship.src_type == "note"))]
    return d


def _save_note(ws: Workspace, n: m.Note, *, new: bool) -> None:
    integ = internal_integration(ws.db, ws.user_id, "notes")
    if n.source_item_id is None:
        si = m.SourceItem(user_id=ws.user_id, integration_id=integ.id, external_id=f"note:{n.id}", kind="note", content_hash=stable_hash(n.body))
        ws.db.add(si)
        ws.db.flush()
        n.source_item_id = si.id
    else:
        existing = ws.db.get(m.SourceItem, n.source_item_id)
        if existing:
            existing.content_hash = stable_hash(n.body)
    publish(ws.db, ws.user_id, SOURCE_ITEM_UPSERTED, {"source_item_id": n.source_item_id, "kind": "note"})
    ws.db.commit()
    dispatch(ws.db, ws.user_id)


@router.post("/notes")
def create_note(body: NoteIn, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    if body.project_id:
        p = ws.db.get(m.Project, body.project_id)
        if p is None or p.user_id != ws.user_id:
            raise HTTPException(404, "project not found")
    n = m.Note(user_id=ws.user_id, title=body.title, body=body.body, tags=body.tags, project_id=body.project_id, pinned=body.pinned)
    ws.db.add(n)
    ws.db.flush()
    _save_note(ws, n, new=True)
    ws.db.refresh(n)
    return note_dict(ws.db, n)


@router.put("/notes/{nid}")
def update_note(nid: str, body: NoteIn, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    n = ws.db.get(m.Note, nid)
    if not n or n.user_id != ws.user_id:
        raise HTTPException(404, "not found")
    if body.project_id:
        p = ws.db.get(m.Project, body.project_id)
        if p is None or p.user_id != ws.user_id:
            raise HTTPException(404, "project not found")
    from app.ingestion.purge import purge_content

    # derived data is rebuilt; the user's text is stored exactly as written
    n.title, n.body, n.tags, n.project_id, n.pinned = body.title, body.body, body.tags, body.project_id, body.pinned
    ws.db.flush()
    purge_content(ws.db, ws.user_id, "note", nid, keep_content=True)  # removed text must not leave stale memories
    _save_note(ws, n, new=False)
    ws.db.refresh(n)
    return note_dict(ws.db, n)


@router.delete("/notes/{nid}")
def delete_note(nid: str, ws: Workspace = Depends(workspace)) -> dict[str, bool]:
    n = ws.db.get(m.Note, nid)
    if not n or n.user_id != ws.user_id:
        raise HTTPException(404, "not found")
    si_id = n.source_item_id
    from app.ingestion.purge import purge_content

    purge_content(ws.db, ws.user_id, "note", nid)
    if si_id:
        si = ws.db.get(m.SourceItem, si_id)
        if si:
            ws.db.delete(si)
    ws.db.commit()
    _ = SOURCE_ITEM_DELETED
    return {"ok": True}
