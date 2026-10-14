"""Store, parse and locate uploaded/synced documents."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import models as m
from app.documents.chunking import ChunkSpec, chunk_blocks
from app.documents.parsers import ParsedDocument, ParseError, parse
from app.documents.validation import storage_path, validate_upload


def store_document_bytes(db: Session, user_id: str, si: m.SourceItem, filename: str, content: bytes, *,
                         title: str | None = None, author: str | None = None, authored_at: datetime | None = None,
                         declared_mime: str | None = None) -> m.Document:
    s = get_settings()
    v = validate_upload(filename, content, declared_mime, s.max_upload_mb * 1024 * 1024)
    path = storage_path(s.data_dir, user_id, v.storage_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    doc = m.Document(user_id=user_id, source_item_id=si.id, title=title or Path(v.original_filename).stem,
                     original_filename=v.original_filename, storage_name=v.storage_name, mime_type=v.mime_type,
                     size_bytes=v.size, sha256=v.sha256, status="processing", authored_at=authored_at)
    try:
        parsed = parse(content, v.extension, v.original_filename)
        doc.text = parsed.text
        doc.page_count = parsed.page_count
        doc.title = title or (parsed.title if parsed.title and len(parsed.title) < 200 else doc.title)
        meta = dict(parsed.metadata)
        if author:
            meta["author"] = author
        doc.doc_metadata = meta
    except ParseError as exc:
        doc.status, doc.error = "error", str(exc)
    db.add(doc)
    db.flush()
    return doc


def load_parsed(doc: m.Document) -> ParsedDocument | None:
    s = get_settings()
    try:
        p = storage_path(s.data_dir, doc.user_id, doc.storage_name)
        return parse(p.read_bytes(), Path(doc.storage_name).suffix, doc.original_filename)
    except (OSError, ParseError, ValueError):
        return None


def chunks_for(doc: m.Document) -> list[ChunkSpec]:
    parsed = load_parsed(doc)
    if parsed is None:
        from app.documents.chunking import chunk_plain

        return chunk_plain(doc.text or doc.title)
    return chunk_blocks(parsed.blocks)


def delete_file(doc: m.Document) -> None:
    s = get_settings()
    try:
        storage_path(s.data_dir, doc.user_id, doc.storage_name).unlink(missing_ok=True)
    except ValueError:
        pass
