# Test report

Final runs on 2026-10-15 against the code in this repository. Nothing below is estimated; each line is the output of the command shown.

| Suite | Command | Result |
|---|---|---|
| Backend unit + integration | `cd backend && pytest` | **165 passed**, 0 failed (≈23 s) |
| Frontend unit | `cd frontend && npx vitest run` | **13 passed**, 0 failed |
| End-to-end | `cd frontend && npx playwright test` against `docker compose up --build` | **19 passed**, 0 failed (16.6 s) |
| Python lint | `ruff check .` | clean |
| Python types | `mypy app` | 0 errors in 91 files |
| TypeScript lint / types | `eslint .`, `tsc --noEmit` | clean |

The end-to-end run used `AUTH_RATE_LIMIT_PER_MINUTE=1000` because the suite signs in many times per minute from one IP;
the stack was restarted with the default limit (10/min) afterwards.

## What the backend tests cover

Integration tests run against a real PostgreSQL with pgvector; the schema is built by running the Alembic migrations from scratch.

| File | Tests | Covers |
|---|---|---|
| unit/test_commitment_extraction.py | 23 | promises, requests, intentions, completions, negatives, deadlines, pronoun actors |
| unit/test_temporal.py | 17 | relative and absolute dates, past/future preference, ranges, time zones |
| unit/test_llm_adapters.py | 9 | Ollama and OpenAI-compatible adapters (mocked HTTP), structured output retries, gateway routing |
| unit/test_connectors.py | 8 | local folder roots, Gmail/Calendar parsing and incremental sync against mocked APIs |
| unit/test_entity_resolution.py | 7 | auto-link, suggest-only, keep-apart, merge and split |
| unit/test_commitment_resolution.py | 6 | fulfilled, overdue, cancelled, uncertain, cross-project penalties |
| unit/test_graph_memory.py | 6 | temporal edges, supersession, as-of queries, memory lifecycle |
| unit (other) | 35 | documents, entities, decisions and facts, privacy policy, ranking, security core, text, tool permissions |
| integration/test_api.py | 35 | the API through HTTP: auth, CSRF, cross-user 404s, uploads, export and delete |
| integration/test_agent.py | 6 | plan/execute/verify loop, approvals, injection handling |
| integration/test_pipelines.py | 6 | sync → events → extraction → graph → resolution end to end |
| integration/test_audit_regressions.py | 7 | regressions for the audit findings; others live in test_api and the connector tests |

## End-to-end journeys

Login errors, protected-route redirects, the morning briefing with evidence, cited assistant answers that open their source,
refusal of bulk exfiltration, temporal employment history, project health, progressive graph expansion, confirming an AI-suggested
task, persisting privacy mode, meeting briefs, follow-up feedback, grouped search with retrieval channels, full onboarding of a new
user, every page rendering without console errors, no horizontal scroll at phone width, keyboard access (skip link and command
palette), offline state, and dark mode.

## Failures found by tests and fixed during development

* Extractor false positives and negatives ("owns", "be back", "drop", pronoun actors) and a crash on "have X ready", found by the held-out set.
* "In March" resolved to the following year; fixed with a past/future preference.
* Duplicate commitments and decisions across a thread; fixed by consolidation.
* A wrong cross-project fulfilment; fixed with conflicting-object and different-project penalties.
* List environment variables failed to parse in settings.
* Worker and beat health checks failed in Docker.
* All users shared one rate-limit bucket behind the frontend proxy, which also broke the E2E run.
* A React effect returned a Promise from `scrollIntoView` in Chrome.
* Several E2E selector and onboarding navigation issues.
* mypy went from 108 errors to 0.
* Running the evaluation inside the Docker stack produced near-zero retrieval and resolution scores. The deployment sends
  events to Celery, so the evaluation scored a workspace the workers had not processed yet. Evaluations and the benchmark now
  always process their workspace synchronously (regression test added). The Docker run then reproduced the local results; vector
  MRR differed by 0.1 point (71.0% vs 71.1%), which is floating-point variation between the container and the host.
* The same run showed the evaluation results could not be written in the container (read-only app directory); results now go to
  `EVAL_RESULTS_DIR` on the data volume.
* The evaluation page displayed counts of 0 or 1 (e.g. "unresolved mentions: 1") as percentages; fixed.

## Not tested

* Gmail and Google Calendar against a live Google account (only mocked APIs).
* Real cloud LLM providers (only mocked HTTP; no API key was used).
* Concurrent multi-user load.
* Browsers other than Chromium.
* The GitHub Actions workflow had not run on GitHub at the time of writing.
