# Performance report

Measured 2026-10-14T20:09:59 UTC on macOS-26.6.2-arm64-arm-64bit, 12 CPUs, Python 3.11.15 (`python -m evals.perf`).

* Embedding throughput (fastembed:BAAI/bge-small-en-v1.5): **334.4 texts/s** (512 texts in 1.53 s).
* Full pipeline (sync → events → extraction → resolution → graph → embeddings) on 1000 emails: **16.2 emails/s** (store 1.39 s, process 60.33 s; 846 commitments extracted).

Latency by data size (memory objects = chunks with embeddings, their emails and graph edges):

| Objects | Vector search p50/p95 | Keyword p50/p95 | Hybrid p50/p95 | Graph neighbourhood p50 | Dashboard briefing p50 | Assistant (extractive) p50 | HNSW used |
|---|---|---|---|---|---|---|---|
| 1,000 | 6.4 / 27.73 ms | 2.95 / 7.18 ms | 14.24 / 59.35 ms | 3.07 ms | 2.92 ms | 10.03 ms | False |
| 10,000 | 32.18 / 52.09 ms | 6.48 / 16.98 ms | 47.39 / 211.71 ms | 3.75 ms | 3.04 ms | 14.71 ms | True |
| 100,000 | 6.08 / 33.43 ms | 23.88 / 32.94 ms | 55.08 / 213.31 ms | 6.98 ms | 2.85 ms | 22.04 ms | True |

Local LLM answer latency is reported in the evaluation report (QA p50 with the model). Scale rows use deterministic hashing vectors (same 384-d index) so the 100k load finishes quickly; search latency depends on vector size and index, not on which model produced the vectors. Single-user, single-process measurements; no concurrent load.
