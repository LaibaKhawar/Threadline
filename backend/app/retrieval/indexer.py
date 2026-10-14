"""Chunk + embed content for retrieval. Re-indexing an item replaces its chunks (idempotent)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.ai.embeddings.base import get_embedder
from app.db import models as m
from app.documents.chunking import ChunkSpec


def index_chunks(
    db: Session,
    *,
    user_id: str,
    owner_type: str,
    owner_id: str,
    title: str | None,
    specs: list[ChunkSpec],
    occurred_at: datetime | None,
    project_id: str | None,
    integration_id: str | None,
    header: str = "",
) -> list[m.Chunk]:
    db.execute(delete(m.Chunk).where(m.Chunk.owner_type == owner_type, m.Chunk.owner_id == owner_id))
    if not specs:
        return []
    embedder = get_embedder()
    # Embed with a short header (title / sender / section) so chunks carry their context.
    texts = [f"{header}{(s.section + ': ') if s.section else ''}{s.text}"[:2000] for s in specs]
    vectors = embedder.embed(texts)
    rows = []
    for i, (spec, vec) in enumerate(zip(specs, vectors, strict=True)):
        rows.append(m.Chunk(
            user_id=user_id, owner_type=owner_type, owner_id=owner_id, integration_id=integration_id, ordinal=i,
            text=spec.text, title=title, page=spec.page, section=spec.section, char_start=spec.char_start,
            char_end=spec.char_end, occurred_at=occurred_at, project_id=project_id, embedding=vec.tolist(),
            embedding_model=embedder.model_id,
        ))
    db.add_all(rows)
    return rows


def set_chunk_project(db: Session, owner_type: str, owner_id: str, project_id: str | None) -> None:
    from sqlalchemy import update

    db.execute(update(m.Chunk).where(m.Chunk.owner_type == owner_type, m.Chunk.owner_id == owner_id)
               .values(project_id=project_id))
