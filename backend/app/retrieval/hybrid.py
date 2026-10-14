"""Hybrid retrieval: semantic + keyword + graph + structured, with temporal/metadata filters, fused by
weighted Reciprocal Rank Fusion and lightly reranked.

    channel      what it finds                                         implementation
    vector       paraphrases ("cutover plan" ~ "migration runbook")    pgvector HNSW cosine on chunks
    keyword      exact terms, names, IDs, rare words                   Postgres full-text (ts_rank_cd)
    graph        items linked to the people/projects in the query      relationships table, 1-2 hops
    structured   commitments / decisions / tasks matching intents       SQL over typed tables

Each result keeps the per-channel ranks that produced it, so the UI and evaluation can show *why* an
item was retrieved. Modes `vector`, `keyword`, `graph` run one channel for ablation studies.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, literal_column, or_, select, text
from sqlalchemy.orm import Session

from app.ai.embeddings.base import get_embedder
from app.core.metrics import RETRIEVAL_LATENCY
from app.core.timeutil import ensure_aware
from app.db import models as m
from app.retrieval.query_parser import ParsedQuery, parse_query

RRF_K = 60
WEIGHTS = {"vector": 1.0, "keyword": 1.0, "graph": 0.8, "structured": 1.2}
CONTENT_TYPES = ("email", "event", "document", "note")
STRUCT_TYPES = ("commitment", "decision", "task")


GRAPH_EDGE_LIMIT = 2000  # edges read per graph anchor


@dataclass
class Hit:
    type: str
    id: str
    title: str
    snippet: str
    occurred_at: datetime | None
    integration_id: str | None = None
    project_id: str | None = None
    location: dict[str, Any] = field(default_factory=dict)
    channels: dict[str, int] = field(default_factory=dict)  # channel -> rank (1-based)
    score: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, str]:
        return (self.type, self.id)

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.type, "id": self.id, "title": self.title, "snippet": self.snippet,
            "occurred_at": self.occurred_at.isoformat() if self.occurred_at else None, "project_id": self.project_id,
            "location": self.location, "channels": self.channels, "score": round(self.score, 5), **self.extra,
        }


@dataclass
class SearchResult:
    query: ParsedQuery
    hits: list[Hit]
    timings_ms: dict[str, float]
    mode: str

    def grouped(self) -> dict[str, list[dict[str, Any]]]:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for h in self.hits:
            groups[h.type].append(h.as_dict())
        return dict(groups)


class HybridRetriever:
    def __init__(self, db: Session, user_id: str, *, now: datetime, tz: str = "UTC", self_person_id: str | None = None) -> None:
        self.db = db
        self.user_id = user_id
        self.now = now
        self.tz = tz
        self.self_person_id = self_person_id

    # ------------------------------------------------------------------------------------ public
    def search(self, query: str, *, k: int = 20, mode: str = "hybrid", types: set[str] | None = None,
               parsed: ParsedQuery | None = None, use_time_filter: bool = True,
               allowed_integrations: set[str] | None = None) -> SearchResult:
        pq = parsed or parse_query(self.db, self.user_id, query, now=self.now, tz=self.tz, self_person_id=self.self_person_id)
        want = types or (pq.types if pq.types else None)
        tstart, tend = (pq.time_start, pq.time_end) if use_time_filter else (None, None)
        timings: dict[str, float] = {}
        ranked: dict[str, list[Hit]] = {}
        channels = {"hybrid": ("vector", "keyword", "graph", "structured"), "vector": ("vector",),
                    "keyword": ("keyword",), "graph": ("graph",)}[mode]
        for ch in channels:
            t0 = time.perf_counter()
            fn = getattr(self, f"_{ch}")
            ranked[ch] = fn(pq, want, tstart, tend, k * 3)
            dt = time.perf_counter() - t0
            timings[ch] = round(dt * 1000, 2)
            RETRIEVAL_LATENCY.labels(ch).observe(dt)
        t0 = time.perf_counter()
        fused = self._fuse(ranked, pq)
        if allowed_integrations is not None:
            fused = [h for h in fused if h.integration_id is None or h.integration_id in allowed_integrations]
        timings["fuse"] = round((time.perf_counter() - t0) * 1000, 2)
        return SearchResult(pq, fused[:k], timings, mode)

    # ---------------------------------------------------------------------------------- filters
    def _chunk_filters(self, pq: ParsedQuery, want: set[str] | None, tstart: datetime | None, tend: datetime | None) -> list[Any]:
        f: list[Any] = [m.Chunk.user_id == self.user_id]
        if want:
            ct = [t for t in want if t in CONTENT_TYPES]
            if ct:
                f.append(m.Chunk.owner_type.in_(ct))
            elif not ({"commitment", "decision", "task"} & want):
                pass
        if tstart:
            f.append(m.Chunk.occurred_at >= tstart)
        if tend:
            f.append(m.Chunk.occurred_at <= tend)
        f.append(or_(m.Chunk.occurred_at.is_(None), m.Chunk.occurred_at <= self.now))
        if pq.project_ids:
            f.append(or_(m.Chunk.project_id.in_(pq.project_ids), m.Chunk.project_id.is_(None)))
        return f

    def _chunk_hits(self, rows: list[tuple[m.Chunk, float]]) -> list[Hit]:
        """Collapse chunk rows to their owner (best chunk wins), preserving rank order."""
        seen: dict[tuple[str, str], Hit] = {}
        out: list[Hit] = []
        for ch, score in rows:
            key = (ch.owner_type, ch.owner_id)
            if key in seen:
                continue
            h = Hit(type=ch.owner_type, id=ch.owner_id, title=ch.title or "", snippet=ch.text[:320], occurred_at=ch.occurred_at,
                    integration_id=ch.integration_id, project_id=ch.project_id,
                    location={"chunk_id": ch.id, "page": ch.page, "section": ch.section, "char_start": ch.char_start,
                              "char_end": ch.char_end}, extra={"raw_score": round(float(score), 4)})
            seen[key] = h
            out.append(h)
        return out

    # --------------------------------------------------------------------------------- channels
    def _vector(self, pq: ParsedQuery, want: set[str] | None, tstart: datetime | None, tend: datetime | None, k: int) -> list[Hit]:
        if want and not (want & set(CONTENT_TYPES)):
            return []
        qtext = pq.raw
        vec = get_embedder().embed_one(qtext, query=True)
        dist = m.Chunk.embedding.cosine_distance(vec)
        self.db.execute(text("SET LOCAL hnsw.ef_search = 100"))
        rows = self.db.execute(select(m.Chunk, (1 - dist).label("sim")).where(
            *self._chunk_filters(pq, want, tstart, tend), m.Chunk.embedding.is_not(None)).order_by(dist).limit(k)).all()
        return self._chunk_hits([(r[0], r[1]) for r in rows])

    def _keyword(self, pq: ParsedQuery, want: set[str] | None, tstart: datetime | None, tend: datetime | None, k: int) -> list[Hit]:
        if want and not (want & set(CONTENT_TYPES)):
            return []
        terms = pq.keywords or " ".join(pq.person_names + pq.project_names)
        if not terms.strip():
            return []
        # All terms first (selective, cheap to rank on large stores); widen to any term only if that finds too little.
        rows: list[Any] = []
        words = terms.split()
        for query_text in ([" ".join(words), " or ".join(words)] if len(words) > 1 else [terms]):
            tsq = func.websearch_to_tsquery("english", query_text)
            rank = func.ts_rank_cd(m.Chunk.tsv, tsq, 32)
            found = self.db.execute(select(m.Chunk, rank.label("r")).where(
                *self._chunk_filters(pq, want, tstart, tend), m.Chunk.tsv.op("@@")(tsq)).order_by(rank.desc()).limit(k)).all()
            seen = {r[0].id for r in rows}
            rows += [r for r in found if r[0].id not in seen]
            if len(rows) >= min(k, 10):
                break
        return self._chunk_hits([(r[0], r[1]) for r in rows])

    def _graph(self, pq: ParsedQuery, want: set[str] | None, tstart: datetime | None, tend: datetime | None, k: int) -> list[Hit]:
        anchors = [("person", p) for p in pq.person_ids] + [("project", p) for p in pq.project_ids] + [("organization", o) for o in pq.org_ids]
        if not anchors:
            return []
        R = m.Relationship
        scores: dict[tuple[str, str], float] = defaultdict(float)
        rel_weight = {"SENT": 1.0, "SENT_TO": 0.8, "PARTICIPATES_IN": 1.0, "BELONGS_TO": 0.9, "MENTIONS": 0.7, "CREATED": 1.0,
                      "COMMITTED_TO": 1.2, "ASSIGNED_TO": 1.1, "FOR": 0.8, "DECIDED_IN": 0.6, "REFERENCES": 0.5}
        node_types = set(CONTENT_TYPES) | set(STRUCT_TYPES)
        per_anchor: list[set[tuple[str, str]]] = []
        for at, aid in anchors:
            # Busy people have tens of thousands of SENT edges; the most recent ones are enough to rank on.
            rows = self.db.execute(select(R.src_type, R.src_id, R.dst_type, R.dst_id, R.rel_type).where(
                R.user_id == self.user_id, R.status == "active",
                or_(and_(R.src_type == at, R.src_id == aid), and_(R.dst_type == at, R.dst_id == aid)))
                .order_by(R.observed_at.desc()).limit(GRAPH_EDGE_LIMIT)).all()
            linked: set[tuple[str, str]] = set()
            for st, sid, dt, did, rel in rows:
                other = (dt, did) if (st, sid) == (at, aid) else (st, sid)
                if other[0] in node_types:
                    scores[other] += rel_weight.get(rel, 0.5)
                    linked.add(other)
            per_anchor.append(linked)
        # items linked to *all* anchors (e.g. Sarah AND Phoenix) rank above items linked to one
        if len(anchors) > 1:
            for node in set.intersection(*per_anchor):
                scores[node] += 2.0
        # materialize only the best-scored candidates
        top = sorted(scores.items(), key=lambda kv: -kv[1])[: max(k * 8, 200)]
        hits = self._materialize(top, want, tstart, tend)
        hits.sort(key=lambda h: (-scores[h.key], -(h.occurred_at.timestamp() if h.occurred_at else 0)))
        return hits[:k]

    def _structured(self, pq: ParsedQuery, want: set[str] | None, tstart: datetime | None, tend: datetime | None, k: int) -> list[Hit]:
        out: list[Hit] = []
        types = want or set()
        kw = [w for w in pq.keywords.split() if len(w) > 2]
        intents = pq.intents
        if not types and not intents and not kw:
            return out
        if "commitment" in types or intents & {"waiting_on", "my_promises", "unanswered"} or (not types and kw):
            q = select(m.Commitment).where(m.Commitment.user_id == self.user_id, m.Commitment.detected_at <= self.now)
            if pq.person_ids:
                q = q.where(or_(m.Commitment.actor_person_id.in_(pq.person_ids), m.Commitment.recipient_person_id.in_(pq.person_ids)))
            if "waiting_on" in intents:
                q = q.where(m.Commitment.status.in_(["OPEN", "OVERDUE"]), m.Commitment.actor_person_id != self.self_person_id)
            if "my_promises" in intents and self.self_person_id:
                q = q.where(m.Commitment.actor_person_id == self.self_person_id, m.Commitment.kind != "request")
            if pq.project_ids:
                q = q.where(m.Commitment.project_id.in_(pq.project_ids))
            if tstart:
                q = q.where(m.Commitment.detected_at >= tstart)
            if tend:
                q = q.where(m.Commitment.detected_at <= tend)
            if kw and not (pq.person_ids or pq.project_ids or intents):
                q = q.where(or_(*[m.Commitment.description.ilike(f"%{w}%") for w in kw]))
            rows = list(self.db.scalars(q.order_by(m.Commitment.detected_at.desc()).limit(k)))
            rows.sort(key=lambda c: -sum(1 for w in kw if w in f"{c.description} {c.evidence_span}".lower()))
            for c in rows:
                out.append(Hit("commitment", c.id, c.description, c.evidence_span[:300], c.detected_at, project_id=c.project_id,
                               extra={"status": c.status, "due_at": c.due_at.isoformat() if c.due_at else None,
                                      "source_type": c.source_type, "source_id": c.source_id, "kind": c.kind}))
        if "decision" in types or intents & {"superseded"}:
            q2 = select(m.Decision).where(m.Decision.user_id == self.user_id, m.Decision.decided_at <= self.now)
            if pq.project_ids:
                q2 = q2.where(m.Decision.project_id.in_(pq.project_ids))
            if "superseded" in intents:
                q2 = q2.where(m.Decision.status == "superseded")
            if tstart:
                q2 = q2.where(or_(m.Decision.decided_at >= tstart))
            if tend:
                q2 = q2.where(m.Decision.decided_at <= tend)
            drows = list(self.db.scalars(q2.order_by(m.Decision.decided_at.desc()).limit(k)))
            drows.sort(key=lambda d: -sum(1 for w in kw if w in f"{d.topic} {d.chosen} {' '.join(d.rejected)} {d.statement}".lower()))
            for d in drows:
                out.append(Hit("decision", d.id, f"{d.topic}: {d.chosen}", d.statement[:300], d.decided_at, project_id=d.project_id,
                               extra={"status": d.status, "source_type": d.source_type, "source_id": d.source_id}))
        if "task" in types or "blocked" in intents:
            q3 = select(m.Task).where(m.Task.user_id == self.user_id, m.Task.status != "dismissed")
            if "blocked" in intents:
                q3 = q3.where(m.Task.status == "blocked")
            if pq.project_ids:
                q3 = q3.where(m.Task.project_id.in_(pq.project_ids))
            for t in self.db.scalars(q3.order_by(m.Task.due_at.asc().nullslast()).limit(k)):
                out.append(Hit("task", t.id, t.title, t.blocked_reason or t.evidence_span or t.description or "", t.due_at or t.created_at,
                               project_id=t.project_id, extra={"status": t.status}))
        return out

    # -------------------------------------------------------------------------- materialisation
    def _materialize(self, nodes: list[tuple[tuple[str, str], float]], want: set[str] | None,
                     tstart: datetime | None, tend: datetime | None) -> list[Hit]:
        by_type: dict[str, list[str]] = defaultdict(list)
        for (t, i), _ in nodes:
            if want and t not in want and not (t in CONTENT_TYPES and want & {"commitment", "decision"} and False):
                continue
            by_type[t].append(i)
        hits: list[Hit] = []

        def in_time(dt: datetime | None) -> bool:
            dt = ensure_aware(dt)
            if dt is None:
                return True
            if dt > self.now:
                return False
            return (not tstart or dt >= tstart) and (not tend or dt <= tend)

        integ = self._integration_of
        if ids := by_type.get("email"):
            for e in self.db.scalars(select(m.Email).where(m.Email.id.in_(ids), m.Email.user_id == self.user_id)):
                if in_time(e.sent_at):
                    hits.append(Hit("email", e.id, e.subject, e.body[:300], e.sent_at, integ("email", e.id), e.project_id))
        if ids := by_type.get("event"):
            for ev in self.db.scalars(select(m.CalendarEvent).where(m.CalendarEvent.id.in_(ids), m.CalendarEvent.user_id == self.user_id)):
                if in_time(ev.start_at):
                    hits.append(Hit("event", ev.id, ev.title, (ev.notes or ev.description or "")[:300], ev.start_at,
                                    integ("event", ev.id), ev.project_id))
        if ids := by_type.get("document"):
            for d in self.db.scalars(select(m.Document).where(m.Document.id.in_(ids), m.Document.user_id == self.user_id)):
                when = ensure_aware(d.authored_at) or d.created_at
                if in_time(when):
                    hits.append(Hit("document", d.id, d.title, d.text[:300], when, integ("document", d.id), d.project_id))
        if ids := by_type.get("note"):
            for n in self.db.scalars(select(m.Note).where(m.Note.id.in_(ids), m.Note.user_id == self.user_id)):
                hits.append(Hit("note", n.id, n.title, n.body[:300], n.updated_at, integ("note", n.id), n.project_id))
        if ids := by_type.get("commitment"):
            for c in self.db.scalars(select(m.Commitment).where(m.Commitment.id.in_(ids), m.Commitment.user_id == self.user_id)):
                if in_time(c.detected_at):
                    hits.append(Hit("commitment", c.id, c.description, c.evidence_span[:300], c.detected_at, project_id=c.project_id,
                                    extra={"status": c.status, "due_at": c.due_at.isoformat() if c.due_at else None,
                                           "source_type": c.source_type, "source_id": c.source_id, "kind": c.kind}))
        if ids := by_type.get("decision"):
            for d2 in self.db.scalars(select(m.Decision).where(m.Decision.id.in_(ids), m.Decision.user_id == self.user_id)):
                if in_time(d2.decided_at):
                    hits.append(Hit("decision", d2.id, f"{d2.topic}: {d2.chosen}", d2.statement[:300], d2.decided_at, project_id=d2.project_id,
                                    extra={"status": d2.status, "source_type": d2.source_type, "source_id": d2.source_id}))
        if ids := by_type.get("task"):
            for tk in self.db.scalars(select(m.Task).where(m.Task.id.in_(ids), m.Task.user_id == self.user_id)):
                hits.append(Hit("task", tk.id, tk.title, tk.evidence_span or "", tk.due_at or tk.created_at, project_id=tk.project_id,
                                extra={"status": tk.status}))
        return hits

    _integ_cache: dict[tuple[str, str], str | None]

    def _integration_of(self, owner_type: str, owner_id: str) -> str | None:
        if not hasattr(self, "_integ_cache"):
            self._integ_cache = {}
        key = (owner_type, owner_id)
        if key not in self._integ_cache:
            from app.privacy.policy import integration_of

            self._integ_cache[key] = integration_of(self.db, owner_type, owner_id)
        return self._integ_cache[key]

    # ------------------------------------------------------------------------------------ fusion
    def _fuse(self, ranked: dict[str, list[Hit]], pq: ParsedQuery) -> list[Hit]:
        merged: dict[tuple[str, str], Hit] = {}
        for ch, hits in ranked.items():
            w = WEIGHTS[ch]
            for rank, h in enumerate(hits, start=1):
                cur = merged.get(h.key)
                if cur is None:
                    cur = h
                    merged[h.key] = cur
                elif not cur.location and h.location:
                    cur.location, cur.snippet = h.location, h.snippet  # prefer chunk-level provenance
                cur.channels[ch] = rank
                cur.score += w / (RRF_K + rank)
        hits = list(merged.values())
        anchored = bool(pq.person_ids or pq.project_ids or pq.org_ids)
        linked = {h.key for h in ranked.get("graph", [])} | {h.key for h in ranked.get("structured", [])}
        for h in hits:
            # When the query names people/projects, items not connected to them in the graph are demoted.
            if anchored and "graph" in ranked and h.key not in linked and not (
                    pq.project_ids and h.project_id in pq.project_ids):
                h.score *= 0.4
            # rerank boosts: agreement across channels, recency for "latest" queries
            if len(h.channels) >= 2:
                h.score *= 1.0 + 0.1 * (len(h.channels) - 1)
            if "latest" in pq.intents and h.occurred_at:
                age_days = max(0.0, (self.now - ensure_aware(h.occurred_at)).total_seconds() / 86400)  # type: ignore[operator]
                h.score *= 1.0 + max(0.0, 0.5 - age_days / 120)
            if h.type in ("email", "document", "event", "note") and h.integration_id is None:
                h.integration_id = self._integration_of(h.type, h.id)
        hits.sort(key=lambda h: -h.score)
        return hits


_ = (literal_column, func)
