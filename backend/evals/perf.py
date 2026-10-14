"""Performance benchmark.

    python -m evals.perf                 # 1k / 10k / 100k
    python -m evals.perf --sizes 1000    # quick

Measures, on this machine:
  * full-pipeline sync throughput (1,000 synthetic emails through sync -> events -> extraction -> graph -> embeddings)
  * embedding throughput of the configured local embedder
  * search latency (vector / keyword / hybrid), graph neighbourhood latency, dashboard and assistant latency
    at 1k / 10k / 100k memory objects (chunks with embeddings plus their emails and graph edges)
Scale rows are bulk-inserted with the deterministic hashing embedder so the 100k run finishes in minutes;
search latency depends on vector dimension and index, not on which model produced the vectors.
Results go to evals/results/perf.json.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import insert, select, text

from app.ai.embeddings.base import HashingEmbedder, get_embedder
from app.db import models as m
from app.db.session import SessionLocal
from app.services.accounts import create_user

# EVAL_RESULTS_DIR lets read-only installs (the Docker image) write results to the data volume
RESULTS = Path(os.environ.get("EVAL_RESULTS_DIR") or Path(__file__).resolve().parent / "results")
WORDS = ["migration", "runbook", "budget", "approval", "pricing", "onboarding", "pilot", "proposal", "architecture", "decision", "deadline", "review", "contract", "vendor", "security", "backfill", "cluster", "forecast", "dashboard", "metrics", "launch", "roadmap", "hiring", "rubric", "validation", "dataset"]
NAMES = ["Sarah Chen", "Ahmed Khan", "Daniel Smith", "Maya Rodriguez", "Priya Nair", "John Park", "Laiba Hassan", "Tom Becker"]


def pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(p * len(xs)))], 2)


def timeit(fn, n: int = 20) -> dict[str, float]:  # type: ignore[no-untyped-def]
    xs = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        xs.append((time.perf_counter() - t0) * 1000)
    return {"p50_ms": pct(xs, 0.5), "p95_ms": pct(xs, 0.95), "mean_ms": round(statistics.mean(xs), 2)}


def sentence(rng: random.Random) -> str:
    who = rng.choice(NAMES)
    return f"{who} will {rng.choice(['send', 'review', 'share', 'finish'])} the {rng.choice(WORDS)} {rng.choice(WORDS)} by Friday. " \
           f"We discussed {' '.join(rng.choice(WORDS) for _ in range(12))}."


def pipeline_throughput(n: int = 1000) -> dict[str, Any]:
    from app.connectors.base import NormalizedEmail
    from app.domain.events import dispatch
    from app.ingestion.sync import _upsert

    db = SessionLocal()
    user = create_user(db, email=f"perf-pipe-{uuid.uuid4().hex[:8]}@example.com", password="perf-password-123", display_name="Perf User")
    integ = m.Integration(user_id=user.id, kind="demo", name="perf", config={})
    db.add(integ)
    db.commit()
    rng = random.Random(1)
    base = datetime(2026, 9, 1, tzinfo=UTC)
    items = []
    for i in range(n):
        who = rng.choice(NAMES)
        items.append(NormalizedEmail(external_id=f"p{i}", message_id=f"<p{i}@perf>", subject=f"{rng.choice(WORDS).title()} update {i}",
                                     body=f"Hi Alex,\n\n{sentence(rng)}\n\n{who}", from_addr=who.split()[0].lower() + "@perf.example",
                                     from_name=who, to=[{"name": "Perf User", "email": user.email}], cc=[], sent_at=base + timedelta(minutes=i)))
    t0 = time.perf_counter()
    for it in items:
        _upsert(db, integ, it)
    db.commit()
    t_store = time.perf_counter() - t0
    t1 = time.perf_counter()
    from app.domain.events import eager_events

    with eager_events():
        dispatch(db, user.id)
    t_proc = time.perf_counter() - t1
    out = {"emails": n, "store_seconds": round(t_store, 2), "process_seconds": round(t_proc, 2),
           "end_to_end_items_per_second": round(n / (t_store + t_proc), 1), "embedder": get_embedder().model_id,
           "commitments_extracted": db.query(m.Commitment).filter(m.Commitment.user_id == user.id).count()}
    db.delete(user)
    db.commit()
    db.close()
    return out


def embedding_throughput() -> dict[str, Any]:
    e = get_embedder()
    rng = random.Random(2)
    texts = [sentence(rng) for _ in range(512)]
    e.embed(texts[:8])
    t0 = time.perf_counter()
    e.embed(texts)
    dt = time.perf_counter() - t0
    return {"embedder": e.model_id, "texts": len(texts), "seconds": round(dt, 2), "texts_per_second": round(len(texts) / dt, 1)}


def scale(n: int) -> dict[str, Any]:
    from app.agent.runtime import AgentRuntime
    from app.ingestion.workspace import Workspace
    from app.intelligence.briefs import daily_briefing
    from app.memory.graph import GraphService
    from app.retrieval.hybrid import HybridRetriever

    db = SessionLocal()
    user = create_user(db, email=f"perf-{n}-{uuid.uuid4().hex[:6]}@example.com", password="perf-password-123", display_name="Perf User")
    db.commit()
    rng = random.Random(n)
    people = []
    for nm in NAMES:
        p = m.Person(user_id=user.id, display_name=nm, primary_email=nm.split()[0].lower() + "@perf.example")
        db.add(p)
        people.append(p)
    db.flush()
    for p in people:  # aliases so the query parser can resolve names (graph channel)
        db.add(m.PersonAlias(user_id=user.id, person_id=p.id, alias=p.display_name, alias_norm=p.display_name.lower(), kind="name"))
    db.flush()
    hasher = HashingEmbedder()
    base = datetime(2025, 1, 1, tzinfo=UTC)
    t0 = time.perf_counter()
    batch = 2000
    for start in range(0, n, batch):
        size = min(batch, n - start)
        texts = [sentence(rng) for _ in range(size)]
        vecs = hasher.embed(texts)
        emails: list[dict[str, Any]] = []
        chunks: list[dict[str, Any]] = []
        rels: list[dict[str, Any]] = []
        for i in range(size):
            eid = str(uuid.uuid4())
            when = base + timedelta(minutes=start + i)
            sender = rng.choice(people)
            emails.append({"id": eid, "user_id": user.id, "message_id": f"<{eid}@perf>", "from_addr": sender.primary_email, "from_name": sender.display_name,
                           "subject": f"Update {start + i}", "body": texts[i], "sent_at": when, "direction": "inbound", "to_addrs": [], "cc_addrs": [],
                           "references": [], "attachments": [], "labels": [], "importance": 0.5, "sender_person_id": sender.id})
            chunks.append({"id": str(uuid.uuid4()), "user_id": user.id, "owner_type": "email", "owner_id": eid, "ordinal": 0, "text": texts[i],
                           "title": f"Update {start + i}", "occurred_at": when, "embedding": np.asarray(vecs[i]).tolist(), "embedding_model": hasher.model_id,
                           "char_start": 0, "char_end": len(texts[i])})
            rels.append({"id": str(uuid.uuid4()), "user_id": user.id, "src_type": "person", "src_id": sender.id, "rel_type": "SENT", "dst_type": "email",
                         "dst_id": eid, "observed_at": when, "valid_from": when, "confidence": 1.0, "status": "active", "origin": "structural", "properties": {}})
        db.execute(insert(m.Email), emails)
        db.execute(insert(m.Chunk), chunks)
        db.execute(insert(m.Relationship), rels)
        db.commit()
    load_s = time.perf_counter() - t0
    db.execute(text("ANALYZE chunks; ANALYZE relationships; ANALYZE emails"))
    db.commit()
    ws = Workspace(db, user.id)
    r = HybridRetriever(db, user.id, now=datetime.now(UTC), self_person_id=ws.self_person_id)
    from app.ai.embeddings.base import set_embedder

    prev = get_embedder()
    set_embedder(hasher)  # queries must be embedded in the same space as the bulk rows
    try:
        q = "migration runbook budget approval"
        res = {"vector_search": timeit(lambda: r.search(q, k=20, mode="vector")),
               "keyword_search": timeit(lambda: r.search(q, k=20, mode="keyword")),
               # all four channels: names resolve (graph), no type words, so vector + keyword + graph + structured all run
               "hybrid_search": timeit(lambda: r.search("Sarah Chen migration runbook budget", k=20, mode="hybrid")),
               "graph_neighbourhood": timeit(lambda: GraphService(db, user.id).neighborhood(("person", people[0].id), limit=60)),
               "dashboard_briefing": timeit(lambda: daily_briefing(ws), n=10),
               "assistant_extractive": timeit(lambda: AgentRuntime(db, user.id, use_llm=False).run("What did Sarah Chen promise about the migration runbook?"), n=5)}
    finally:
        set_embedder(prev)
    out = {"objects": n, "bulk_load_seconds": round(load_s, 1), "latency": res,
           "explain_vector_uses_hnsw": "ix_chunks_embedding_hnsw" in str(db.execute(text(
               "EXPLAIN SELECT id FROM chunks ORDER BY embedding <=> (SELECT embedding FROM chunks LIMIT 1) LIMIT 20")).all())}
    db.delete(user)
    db.commit()
    db.close()
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", nargs="*", type=int, default=[1000, 10000, 100000])
    ap.add_argument("--skip-pipeline", action="store_true")
    a = ap.parse_args()
    import platform

    report: dict[str, Any] = {"generated_at": datetime.now(UTC).isoformat(),
                              "machine": {"platform": platform.platform(), "cpu_count": os.cpu_count(), "python": platform.python_version()}}
    print("embedding throughput…")
    report["embedding"] = embedding_throughput()
    print(report["embedding"])
    if not a.skip_pipeline:
        print("pipeline throughput (1,000 emails)…")
        report["pipeline"] = pipeline_throughput(1000)
        print(report["pipeline"])
    report["scale"] = []
    for n in a.sizes:
        print(f"scale {n}…")
        s = scale(n)
        print(json.dumps(s)[:400])
        report["scale"].append(s)
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "perf.json").write_text(json.dumps(report, indent=1))
    db = SessionLocal()
    db.add(m.EvaluationRun(suite="performance", metrics={"pipeline_items_per_s": report.get("pipeline", {}).get("end_to_end_items_per_second"),
                                                          "embed_texts_per_s": report["embedding"]["texts_per_second"],
                                                          **{f"hybrid_p50_ms@{s['objects']}": s["latency"]["hybrid_search"]["p50_ms"] for s in report["scale"]}},
                           details=report, config={"variant": "default"}))
    db.commit()
    _ = select


if __name__ == "__main__":
    main()
