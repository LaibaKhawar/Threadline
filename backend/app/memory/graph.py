"""Temporal property graph stored in PostgreSQL.

Why not Neo4j: one transactional store keeps graph edges, provenance rows and the source records
consistent (no dual-write drift), enforces per-user isolation with the same WHERE clause as every
other query, and traversal depth here is shallow (1-3 hops) where indexed adjacency lookups and
recursive CTEs are fast. See docs/adr/0002-graph-in-postgres.md.

Edges are facts with time: valid_from / valid_to (when true in the world) and observed_at (when we
learned it). Functional relations (a person WORKS_AT one org at a time) close the previous edge
instead of overwriting it.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.metrics import GRAPH_OPS
from app.db import models as m

FUNCTIONAL_RELATIONS = {"WORKS_AT", "HAS_STATUS", "DUE_ON"}

NODE_MODELS: dict[str, Any] = {
    "person": m.Person,
    "organization": m.Organization,
    "project": m.Project,
    "email": m.Email,
    "thread": m.EmailThread,
    "event": m.CalendarEvent,
    "document": m.Document,
    "note": m.Note,
    "task": m.Task,
    "commitment": m.Commitment,
    "decision": m.Decision,
    "topic": m.Topic,
}


def node_label(obj: Any, node_type: str) -> str:
    if node_type == "person":
        return obj.display_name
    if node_type in ("organization", "project", "topic"):
        return obj.name
    if node_type in ("email", "thread"):
        return obj.subject
    if node_type in ("event", "document", "note", "task"):
        return obj.title
    if node_type == "commitment":
        return obj.description[:120]
    if node_type == "decision":
        return f"{obj.topic}: {obj.chosen}"
    return str(getattr(obj, "id", "?"))


@dataclass
class NodeRef:
    type: str
    id: str


class GraphService:
    def __init__(self, db: Session, user_id: str) -> None:
        self.db = db
        self.user_id = user_id

    # ------------------------------------------------------------------------------------- writes
    def add_edge(
        self,
        src: tuple[str, str],
        rel: str,
        dst: tuple[str, str],
        *,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
        observed_at: datetime | None = None,
        confidence: float = 1.0,
        source: tuple[str, str] | None = None,
        span: str | None = None,
        properties: dict[str, Any] | None = None,
        origin: str = "extraction",
    ) -> m.Relationship:
        src_type, src_id = src
        dst_type, dst_id = dst
        source_type, source_id = source if source else (None, None)
        existing = self.db.scalar(
            select(m.Relationship).where(
                m.Relationship.user_id == self.user_id,
                m.Relationship.src_type == src_type, m.Relationship.src_id == src_id,
                m.Relationship.rel_type == rel,
                m.Relationship.dst_type == dst_type, m.Relationship.dst_id == dst_id,
                m.Relationship.source_id == source_id if source_id else m.Relationship.source_id.is_(None),
            )
        )
        if existing:
            if existing.status == "rejected":  # user said this edge is wrong; never resurrect it
                return existing
            existing.confidence = max(existing.confidence, confidence)
            if properties:
                existing.properties = {**(existing.properties or {}), **properties}
            GRAPH_OPS.labels("edge_reinforce").inc()
            return existing
        if rel in FUNCTIONAL_RELATIONS:
            same = self.db.scalar(select(m.Relationship).where(
                m.Relationship.user_id == self.user_id, m.Relationship.src_type == src_type, m.Relationship.src_id == src_id,
                m.Relationship.rel_type == rel, m.Relationship.dst_id == dst_id, m.Relationship.status == "active"))
            new_from = valid_from or observed_at
            if same is not None:
                # The same fact stated again (another email signature, another domain email) reinforces the open
                # period instead of creating a parallel one; an earlier statement moves its start back.
                cur_from = same.valid_from or same.observed_at
                if new_from and cur_from and new_from < cur_from:
                    same.valid_from = new_from
                    if not same.source_id and source_id:
                        same.source_type, same.source_id, same.evidence_span = source_type, source_id, span
                same.confidence = min(0.99, max(same.confidence, confidence) + 0.02)
                props = dict(same.properties or {})
                props["mentions"] = int(props.get("mentions", 1)) + 1
                if properties:
                    props.update({k: v for k, v in properties.items() if k not in props})
                same.properties = props
                self._apply_functional(same)
                GRAPH_OPS.labels("edge_reinforce").inc()
                return same
        if self._rejected_by_user(src, rel, dst):
            edge = m.Relationship(user_id=self.user_id, src_type=src_type, src_id=src_id, rel_type=rel,
                                  dst_type=dst_type, dst_id=dst_id, status="rejected", confidence=confidence,
                                  source_type=source_type, source_id=source_id, evidence_span=span,
                                  observed_at=observed_at or datetime.now().astimezone(), origin=origin)
            self.db.add(edge)
            return edge
        edge = m.Relationship(
            user_id=self.user_id, src_type=src_type, src_id=src_id, rel_type=rel, dst_type=dst_type, dst_id=dst_id,
            valid_from=valid_from, valid_to=valid_to, observed_at=observed_at or datetime.now().astimezone(),
            confidence=confidence, source_type=source_type, source_id=source_id, evidence_span=span,
            properties=properties or {}, origin=origin, status="active",
        )
        self.db.add(edge)
        self.db.flush()
        if rel in FUNCTIONAL_RELATIONS:
            self._apply_functional(edge)
        GRAPH_OPS.labels("edge_add").inc()
        return edge

    def _rejected_by_user(self, src: tuple[str, str], rel: str, dst: tuple[str, str]) -> bool:
        return bool(self.db.scalar(
            select(m.Relationship.id).where(
                m.Relationship.user_id == self.user_id, m.Relationship.status == "rejected",
                m.Relationship.origin == "user", m.Relationship.src_id == src[1], m.Relationship.rel_type == rel,
                m.Relationship.dst_id == dst[1],
            ).limit(1)
        ))

    def _apply_functional(self, new: m.Relationship) -> None:
        """Keep one current value; order facts by valid_from even when observed out of order."""
        others = list(self.db.scalars(
            select(m.Relationship).where(
                m.Relationship.user_id == self.user_id, m.Relationship.src_type == new.src_type,
                m.Relationship.src_id == new.src_id, m.Relationship.rel_type == new.rel_type,
                m.Relationship.id != new.id, m.Relationship.status != "rejected",
            )
        ))
        if not others:
            return
        same_value = [o for o in others if o.dst_id == new.dst_id]
        timeline = sorted([*others, new], key=lambda e: (e.valid_from or e.observed_at))
        # Collapse consecutive same-value facts and close each fact at the next differing one.
        for i, e in enumerate(timeline):
            nxt = next((t for t in timeline[i + 1:] if t.dst_id != e.dst_id), None)
            if nxt is not None:
                e.valid_to = nxt.valid_from or nxt.observed_at
                e.status = "superseded"
                e.superseded_by_id = nxt.id
            else:
                e.valid_to = None if e.status != "rejected" else e.valid_to
                e.status = "active"
                e.superseded_by_id = None
        _ = same_value
        GRAPH_OPS.labels("edge_supersede").inc()

    def reject_edge(self, edge_id: str) -> m.Relationship | None:
        edge = self.db.get(m.Relationship, edge_id)
        if not edge or edge.user_id != self.user_id:
            return None
        edge.status = "rejected"
        edge.origin = "user"
        return edge

    # -------------------------------------------------------------------------------------- reads
    def _temporal_filter(self, as_of: datetime | None):  # type: ignore[no-untyped-def]
        if as_of is None:
            return m.Relationship.status == "active"
        from sqlalchemy import func

        return and_(
            m.Relationship.status != "rejected",
            func.coalesce(m.Relationship.valid_from, m.Relationship.observed_at) <= as_of,
            or_(m.Relationship.valid_to.is_(None), m.Relationship.valid_to > as_of),
        )

    def edges_of(self, node: tuple[str, str], *, rel_types: list[str] | None = None, as_of: datetime | None = None,
                 include_history: bool = False, limit: int = 200) -> list[m.Relationship]:
        t, i = node
        q = select(m.Relationship).where(
            m.Relationship.user_id == self.user_id,
            or_(and_(m.Relationship.src_type == t, m.Relationship.src_id == i),
                and_(m.Relationship.dst_type == t, m.Relationship.dst_id == i)),
        )
        if not include_history:
            q = q.where(self._temporal_filter(as_of))
        else:
            q = q.where(m.Relationship.status != "rejected")
        if rel_types:
            q = q.where(m.Relationship.rel_type.in_(rel_types))
        q = q.order_by(m.Relationship.observed_at.desc()).limit(limit)
        GRAPH_OPS.labels("edges_of").inc()
        return list(self.db.scalars(q))

    def labels(self, refs: list[tuple[str, str]]) -> dict[tuple[str, str], dict[str, Any]]:
        by_type: dict[str, set[str]] = defaultdict(set)
        for t, i in refs:
            by_type[t].add(i)
        out: dict[tuple[str, str], dict[str, Any]] = {}
        for t, ids in by_type.items():
            model = NODE_MODELS.get(t)
            if not model:
                continue
            for obj in self.db.scalars(select(model).where(model.id.in_(ids), model.user_id == self.user_id)):
                info: dict[str, Any] = {"label": node_label(obj, t)}
                for attr in ("sent_at", "start_at", "created_at", "decided_at", "due_at", "status"):
                    v = getattr(obj, attr, None)
                    if v is not None:
                        info[attr] = v.isoformat() if isinstance(v, datetime) else v
                        break
                out[(t, obj.id)] = info
        return out

    def neighborhood(self, node: tuple[str, str], *, rel_types: list[str] | None = None,
                     as_of: datetime | None = None, limit: int = 60,
                     date_from: datetime | None = None, date_to: datetime | None = None) -> dict[str, Any]:
        edges = self.edges_of(node, rel_types=rel_types, as_of=as_of, limit=limit * 3)
        if date_from or date_to:
            edges = [e for e in edges if (not date_from or (e.valid_from or e.observed_at) >= date_from)
                     and (not date_to or (e.valid_from or e.observed_at) <= date_to)]
        edges = edges[:limit]
        refs = {node}
        for e in edges:
            refs.add((e.src_type, e.src_id))
            refs.add((e.dst_type, e.dst_id))
        labels = self.labels(list(refs))
        nodes = [{"id": f"{t}:{i}", "type": t, "ref_id": i, **labels.get((t, i), {"label": "(deleted)"})}
                 for t, i in refs if (t, i) in labels]
        valid = {n["id"] for n in nodes}
        return {
            "center": f"{node[0]}:{node[1]}",
            "nodes": nodes,
            "edges": [self.edge_dict(e) for e in edges
                      if f"{e.src_type}:{e.src_id}" in valid and f"{e.dst_type}:{e.dst_id}" in valid],
        }

    @staticmethod
    def edge_dict(e: m.Relationship) -> dict[str, Any]:
        return {
            "id": e.id, "source": f"{e.src_type}:{e.src_id}", "target": f"{e.dst_type}:{e.dst_id}",
            "type": e.rel_type, "status": e.status, "confidence": e.confidence,
            "valid_from": e.valid_from.isoformat() if e.valid_from else None,
            "valid_to": e.valid_to.isoformat() if e.valid_to else None,
            "observed_at": e.observed_at.isoformat() if e.observed_at else None,
            "evidence": {"source_type": e.source_type, "source_id": e.source_id, "span": e.evidence_span}
            if e.source_id else None,
            "origin": e.origin, "properties": e.properties or {},
        }

    def related_ids(self, node: tuple[str, str], target_type: str, *, rel_types: list[str] | None = None,
                    hops: int = 1, as_of: datetime | None = None) -> set[str]:
        """IDs of nodes of target_type reachable within `hops` (used by graph retrieval)."""
        frontier = {node}
        seen = {node}
        found: set[str] = set()
        for _ in range(hops):
            nxt: set[tuple[str, str]] = set()
            for n in frontier:
                for e in self.edges_of(n, rel_types=rel_types, as_of=as_of, limit=500):
                    other = (e.dst_type, e.dst_id) if (e.src_type, e.src_id) == n else (e.src_type, e.src_id)
                    if other in seen:
                        continue
                    seen.add(other)
                    nxt.add(other)
                    if other[0] == target_type:
                        found.add(other[1])
            frontier = nxt
        return found
