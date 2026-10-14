"""Remove everything derived from a source item (deleted upstream, or deleted by the user)."""

from __future__ import annotations

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.db import models as m
from app.db.base import rowcount


def purge_content(db: Session, user_id: str, owner_type: str, owner_id: str, *, keep_content: bool = False) -> dict[str, int]:
    """Delete what was derived from one content item. Rows the user corrected (commitments they edited,
    decisions they confirmed) survive with their evidence; `keep_content` keeps the item itself (re-processing)."""
    stats: dict[str, int] = {}
    R = m.Relationship
    derived_c = list(db.scalars(select(m.Commitment.id).where(m.Commitment.user_id == user_id, m.Commitment.source_id == owner_id,
                                                              m.Commitment.user_modified.is_(False), m.Commitment.user_confirmed.is_(False))))
    derived_d = list(db.scalars(select(m.Decision.id).where(m.Decision.user_id == user_id, m.Decision.source_id == owner_id,
                                                            m.Decision.user_confirmed.is_(False))))
    kept_ids = set(db.scalars(select(m.Commitment.id).where(m.Commitment.user_id == user_id, m.Commitment.source_id == owner_id,
                                                           (m.Commitment.user_modified.is_(True)) | (m.Commitment.user_confirmed.is_(True)))))
    kept_ids |= set(db.scalars(select(m.Decision.id).where(m.Decision.user_id == user_id, m.Decision.source_id == owner_id,
                                                          m.Decision.user_confirmed.is_(True))))
    derived_t = list(db.scalars(select(m.Task.id).where(m.Task.user_id == user_id, m.Task.source_id == owner_id,
                                                        m.Task.user_modified.is_(False), m.Task.manually_created.is_(False))))
    nodes = [owner_id, *derived_c, *derived_d, *derived_t]
    keep = list(kept_ids) or ["-"]
    stats["relationships"] = rowcount(db.execute(delete(R).where(R.user_id == user_id, R.src_id.not_in(keep), R.dst_id.not_in(keep), or_(
        R.src_id.in_(nodes), R.dst_id.in_(nodes), R.source_id == owner_id)))) or 0
    stats["chunks"] = rowcount(db.execute(delete(m.Chunk).where(m.Chunk.user_id == user_id, m.Chunk.owner_id == owner_id))) or 0
    stats["evidence"] = rowcount(db.execute(delete(m.Evidence).where(m.Evidence.user_id == user_id, m.Evidence.subject_id.not_in(keep), or_(
        m.Evidence.source_id == owner_id, m.Evidence.subject_id.in_(nodes))))) or 0
    db.execute(delete(m.Commitment).where(m.Commitment.id.in_(derived_c), m.Commitment.user_modified.is_(False)))
    for d in db.scalars(select(m.Decision).where(m.Decision.superseded_by_id.in_(derived_d))):
        d.superseded_by_id, d.status = None, "active"
    db.execute(delete(m.Decision).where(m.Decision.id.in_(derived_d)))
    db.execute(delete(m.Task).where(m.Task.id.in_(derived_t)))
    db.execute(delete(m.TimelineEvent).where(m.TimelineEvent.user_id == user_id, m.TimelineEvent.ref_id.in_(nodes)))
    db.execute(delete(m.Memory).where(m.Memory.user_id == user_id, m.Memory.source_id == owner_id))
    db.execute(delete(m.Inference).where(m.Inference.user_id == user_id, m.Inference.subject_id == owner_id))
    db.execute(delete(m.FulfillmentCandidate).where(m.FulfillmentCandidate.user_id == user_id, m.FulfillmentCandidate.source_id == owner_id))
    for c in db.scalars(select(m.Commitment).where(m.Commitment.user_id == user_id, m.Commitment.resolution_source_id == owner_id)):
        c.resolution_source_id = c.resolution_source_type = c.resolution_reason = None
        c.resolution_confidence = None
        if c.status in ("FULFILLED", "CANCELLED") and not c.user_confirmed:
            c.status = "OPEN"
    db.execute(delete(m.CommitmentDueChange).where(m.CommitmentDueChange.user_id == user_id, m.CommitmentDueChange.source_id == owner_id))
    content_models: dict[str, m.ContentModel] = {"email": m.Email, "event": m.CalendarEvent, "document": m.Document, "note": m.Note}
    model = content_models.get(owner_type)
    if model is not None and not keep_content:
        if owner_type == "document":
            from app.documents.service import delete_file

            doc = db.get(m.Document, owner_id)
            if doc is not None and doc.user_id == user_id:
                delete_file(doc)  # the stored original goes too
        db.execute(delete(model).where(model.id == owner_id, model.user_id == user_id))
    return stats


def purge_source_item(db: Session, si: m.SourceItem) -> None:
    sources: tuple[tuple[m.ContentModel, str], ...] = ((m.Email, "email"), (m.CalendarEvent, "event"), (m.Document, "document"), (m.Note, "note"))
    for model, t in sources:
        for oid in db.scalars(select(model.id).where(model.source_item_id == si.id)):
            purge_content(db, si.user_id, t, oid)
