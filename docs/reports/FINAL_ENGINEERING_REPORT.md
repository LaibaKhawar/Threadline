# Final engineering report

Threadline is a local-first personal memory and intelligence platform. This report states what was built, what was measured,
what was not, and what should come next. Numbers come from the files in `backend/evals/results/` and from test runs on
2026-10-14/15; see the [test](TEST_REPORT.md), [evaluation](EVALUATION_REPORT.md) and [performance](PERFORMANCE_REPORT.md) reports.

## 1. Status

| Area | State |
|---|---|
| Ingestion: local folder, uploads, notes, synthetic demo connector | Working, tested |
| Gmail and Google Calendar connectors (read-only OAuth, incremental sync) | Implemented; tested against mocked Google APIs only. **Never run against a live Google account.** |
| Outlook, Drive, Slack, Notion, GitHub, Linear | Listed in the UI as planned; **not implemented** |
| Extraction (entities, dates, commitments, decisions, facts), entity resolution, temporal graph, memories | Working, tested, evaluated |
| Commitment resolution (fulfilled / overdue / cancelled / uncertain) with evidence | Working, tested, evaluated |
| Hybrid retrieval (vector + keyword + graph + structured, RRF) | Working, evaluated |
| Agent runtime with tools, approvals, verifier, output guard | Working, tested, evaluated (including injection) |
| Privacy modes LOCAL / HYBRID / CLOUD, per-source controls, audit log, export, delete | Working, tested. Cloud providers tested with mocked HTTP only; no real cloud key was used |
| Frontend (dashboard, assistant, search, inbox, calendar, documents, notes, people, projects, commitments, decisions, tasks, timeline, graph, activity, integrations, privacy, settings, evaluation, onboarding, login) | Working; covered by unit and end-to-end tests |
| Docker compose, CI workflow, backups | Compose stack built and run locally. The CI workflow is written but has not run on GitHub at the time of writing |

## 2. Architecture

* **One transactional store.** PostgreSQL 16 holds content, chunks with pgvector embeddings (HNSW, 384-d), a generated
  `tsvector` for keyword search, the temporal graph (`relationships` with `valid_from`, `valid_to`, `observed_at`,
  provenance and status) and all derived objects. No dual-write between a graph DB and a document store ([ADR 0002](../adr/0002-graph-in-postgres.md)).
* **Event-driven processing.** Connectors write source items and outbox events in the same transaction. Workers claim events
  atomically (`UPDATE … RETURNING`), so two workers cannot process the same event. Chain: upserted → processed (extract,
  resolve, graph, embed, associate, incremental commitment check) → sync completed (full resolution, proactive insights,
  memory consolidation).
* **Corrections win.** User-confirmed or user-edited rows are preserved through re-sync and are never overridden by automatic
  resolution.
* **AI behind a gateway.** Every model call goes through one gateway that applies the privacy policy, records an audit row and
  validates structured output against Pydantic schemas with retries.

## 3. AI system

* **Embeddings:** `BAAI/bge-small-en-v1.5` via fastembed (ONNX, CPU). A hashing embedder is the fallback when the model is absent.
* **Extraction:** rule-based by default (deterministic, fast, explainable). Optional local-LLM extraction (Ollama,
  `qwen3:4b-instruct-2507-q4_K_M`) whose output is accepted only when grounded in a source span. JSON mode is used because
  grammar-constrained decoding stalled for over 15 minutes per call on this model; switching took held-out LLM accuracy from
  38% to 88.5%.
* **Entity resolution:** scored candidates (email, name forms, organisation, co-occurrence) with three thresholds: auto-merge
  0.90, link 0.80, suggest 0.60. Same name on a different domain is only suggested.
* **Commitment resolution:** later items by the same actor are scored on action/object overlap, attachments, explicit
  completion language, project and time. Fulfilment needs score ≥ 0.70 and a strong signal; 0.45–0.70 becomes a candidate
  for review. Conflicting objects and different projects are penalised.
* **Assistant:** a deterministic planner chooses tools, so text inside retrieved content can never choose an action. Answers are
  composed extractively, or by the local LLM from the cited sources. A verifier removes uncited sentences, flags dates not found
  in the cited source and redacts secrets. An output guard removes action claims, injected instructions and system-prompt echoes.
  Write tools only create proposals that the user approves, edits or rejects.

## 4. Testing

| Suite | Result |
|---|---|
| Backend pytest (unit + integration on real PostgreSQL, migrations from scratch) | 165 passed, 0 failed |
| Frontend Vitest | 13 passed, 0 failed |
| Playwright end-to-end on the production Docker build | 19 passed, 0 failed |
| ruff, mypy (0 errors), ESLint, `tsc --noEmit` | clean |

Details and the history of failures found and fixed are in the [test report](TEST_REPORT.md).

## 5. Evaluation (headline numbers)

| Measure | Result |
|---|---|
| Entity extraction micro-F1 (98 emails) | 93.3% |
| Entity resolution pairwise F1 / precision | 90.9% / 100% (0 false merges) |
| Commitment extraction, demo world (41) | F1 100% |
| Commitment classification, 52 held-out statements: rules / local LLM | 100% / 88.5% |
| Commitment resolution status accuracy (41) | 100% |
| Retrieval R@5 / MRR, hybrid (34 questions) | 72.9% / 83.8% (keyword 68.1% / 76.5%, vector 59.1% / 71.1%) |
| QA factual accuracy (18): local LLM / extractive | 94.4% / 88.9% |
| Temporal QA (7): local LLM / extractive | 100% / 85.7% |
| LLM invalid-citation rate (QA) | 16.7% |
| Prompt injection | 18/18 passed across 3 answer modes, 0 tool executions, 0 secret leaks |
| Permission and privacy checks | 10/10 |
| Agent tool success | 100% of 120 calls |

**Disclosures.**
* The synthetic world, its ground truth, the rules and the question sets were written by the same developer. The demo and QA
  sets were used during development, so those scores are optimistic and close to an upper bound.
* While reviewing outputs, some ground-truth annotations were corrected where they contradicted the written annotation rules,
  and a few real commitments the system found were added to the ground truth.
* The held-out statements were written separately and not tuned on. They exposed one crash (`have X ready`), which was fixed;
  that statement still counts in the score.
* The QA scorer first marked correct dates wrong when written in a different format; it now compares calendar days.
* The LLM cites a source that does not support the sentence in about one of six QA answers. The extractive mode has 0%.
* The reported numbers come from runs on the development machine. The non-LLM suites were also re-run inside the Docker stack and
  matched, except vector MRR (71.0% vs 71.1%). That re-run first exposed a bug: with Celery dispatch the evaluation scored an
  unprocessed workspace and showed near-zero scores. It was fixed before any number was reported from Docker.

## 6. Security

Controls are listed in [docs/security.md](../security.md). An independent code audit on 2026-10-14 found these issues. All
were fixed with regression tests:

1. Local-folder import could read any server path, including through the shared demo account.
2. Tool findings could carry text from a source with AI disabled into a prompt, or into a cloud call.
3. Client-supplied `project_id`s were not checked against the caller.
4. Re-sync could delete user-confirmed rows; automatic resolution could override user status changes.
5. Concurrent workers could process the same event twice.
6. "Delete everything" left files and some derived rows behind.
7. Auth endpoints lacked Origin checks; `/metrics` was public; OAuth start was a GET; evaluation runs were not admin-only.
8. The rate limiter shared one bucket for all clients behind the frontend proxy.

## 7. Performance

Measured on an Apple-silicon laptop (12 CPUs), single user, no concurrent load.

| Measure | Result |
|---|---|
| Embedding throughput | 334.4 texts/s |
| Full pipeline, 1,000 emails | 16.2 emails/s |
| Vector search p50 at 100k objects | 6.08 ms |
| Keyword search p50 at 100k | 23.88 ms |
| Hybrid search p50 / p95 at 100k | 55.08 / 213.31 ms (was 372.6 / 3,014 ms before capping the graph channel) |
| Dashboard briefing p50 at 100k | 2.85 ms |
| Local-LLM QA answer p50 | 3.0 s |

Pipeline throughput rose from under 1 email/s to the figure above by making commitment resolution incremental, adding a cheap
gate before scoring, and computing candidates once. Keyword search at 100k dropped from 350 ms to about 20–24 ms by trying an AND
query before widening to OR. Hybrid search at 100k had a p95 of 3.0 s because the graph channel read every edge of very busy
people (about 12,500 SENT edges each in the synthetic load); it now reads the most recent 2,000 edges per anchor and only
materialises the best-scored candidates. Retrieval quality was unchanged by that cap.

## 8. Privacy

LOCAL ONLY is the default and makes zero cloud calls (tested). HYBRID sends only allow-listed operations and only content from
sources marked cloud-allowed; tool findings are dropped from a prompt if any source was withheld or the call would leave the
machine. Content whose origin cannot be resolved is treated as not allowed. Every model call is written to the audit log.
No telemetry is sent.

## 9. Limitations

* Live Google sync is untested; other connectors are not implemented.
* Rule extraction covers anticipated phrasings; real mail will be messier. LLM extraction is slow on CPU (about 1.2 s per sentence).
* Citations are checked for existence and dates, not for entailment, so a cited but wrong LLM sentence can pass.
* Paraphrase retrieval is weak (hybrid paraphrase R@5 35%).
* The rate limiter is in-process; `LOCAL_IMPORT_ROOTS` is server-wide, not per user.
* Some list endpoints issue per-row queries; tuned for personal scale.
* A person who left an organisation can appear current again if older mail is processed later.
* Performance numbers are single-user; no load test with concurrent users was run.

## 10. Prioritised improvements

1. Run the Gmail and Calendar connectors against a real test account, and record the results.
2. Add an entailment check (local NLI model) to the verifier to cut the LLM's unsupported citations.
3. Add a cross-encoder reranker and query expansion for paraphrase recall.
4. Collect a real, consented, anonymised evaluation set; the current one is author-written.
5. Move rate limiting to Redis and make import roots per user.
6. Remove N+1 queries in list endpoints; add a concurrent load test.
7. Implement Outlook / Microsoft Graph and Google Drive connectors.
