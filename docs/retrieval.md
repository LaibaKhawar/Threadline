# Retrieval

`backend/app/retrieval/hybrid.py`. Plain vector search is one of four channels.

| Channel | Finds | How |
|---|---|---|
| Vector | paraphrases | pgvector HNSW (cosine) over chunk embeddings (bge-small-en-v1.5, 384-d, local ONNX) |
| Keyword | exact terms, names, rare words | Postgres full-text (`websearch_to_tsquery`, `ts_rank_cd`) on a generated `tsvector` |
| Graph | items connected to the people/projects/orgs in the query | 1-hop adjacency over `relationships`, weighted by edge type; items linked to *all* anchors get a bonus |
| Structured | commitments, decisions, tasks matching intents | SQL with person/project/time/status filters |

Query parsing (`query_parser.py`) extracts people (aliases), projects, organisations, source types,
time ranges (tense-aware: "in March" in a question means the past March) and intents.
Temporal and metadata filters apply inside each channel. Results are fused with weighted Reciprocal Rank
Fusion (k=60), boosted when several channels agree, demoted when the query names people/projects the
item is not connected to, and boosted by recency for "latest" queries. Each hit keeps its per-channel
ranks so the UI can show why it was retrieved.

Measured comparison (34 questions with known evidence): see `reports/EVALUATION_REPORT.md`.
