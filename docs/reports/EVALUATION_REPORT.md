# Evaluation report

Generated from `backend/evals/results/latest_llm.json` (run started 2026-10-14T19:58:54 UTC; embedder `fastembed:BAAI/bge-small-en-v1.5`; local model `qwen3:4b-instruct-2507-q4_K_M`). Every number below was computed by `python -m evals.run_all --llm` from the system's actual outputs on the synthetic workspace.

## Entity extraction (rules, 98 emails)

| Type | Precision | Recall | F1 |
|---|---|---|---|
| people | 100.0% | 100.0% | 100.0% |
| organizations | 100.0% | 72.2% | 83.9% |
| projects | 79.2% | 100.0% | 88.4% |
| dates | 97.6% | 97.6% | 97.6% |
| micro | 91.2% | 95.4% | 93.3% |

## Entity resolution (pairwise over 32 mentions: emails, full names, first names)

| Setting | Precision | Recall | F1 |
|---|---|---|---|
| Automatic links only | 100.0% | 83.3% | 90.9% |
| + accepting the suggested merges | 100.0% | 86.1% | 92.5% |

False merges: **0**. Unresolved mentions: 2 (a bare name shared by two identities is deliberately left unresolved). Pending merge suggestions: 1.

## Commitment extraction

Demo world (41 annotated commitments in emails and meeting notes): precision 100.0%, recall 100.0%, F1 100.0%; actor 100.0%, action 100.0%, deadline 92.7%, kind 100.0% (on matched items).

Held-out statements (52 sentences: commitment / request / intention / completed / none):

| Extractor | Accuracy | Macro-F1 | Actionable-detection F1 | Actor | Action | Deadline | Time |
|---|---|---|---|---|---|---|---|
| Rules | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 0.0 s |
| Local LLM (qwen3 4B) | 88.5% | 88.3% | 95.2% | 76.7% | 83.3% | 100.0% | 64.1 s |

## Commitment resolution

Final status accuracy: **100.0%** of 41 ground-truth commitments (OPEN / FULFILLED / OVERDUE / CANCELLED / UNCERTAIN). Per status: FULFILLED 100.0%, OPEN 100.0%, OVERDUE 100.0%, CANCELLED 100.0%, UNCERTAIN 100.0%.

## Retrieval (34 questions with known evidence; 5 are paraphrases with no shared keywords)

| Mode | Recall@5 | Recall@10 | MRR | nDCG@10 | Paraphrase R@5 | p50 latency |
|---|---|---|---|---|---|---|
| vector | 59.1% | 62.5% | 71.1% | 61.8% | 23.3% | 10.0 ms |
| keyword | 68.1% | 71.6% | 76.5% | 68.9% | 33.3% | 3.7 ms |
| graph | 14.3% | 18.0% | 21.4% | 16.0% | 0.0% | 1.4 ms |
| hybrid | 72.9% | 79.1% | 83.8% | 75.2% | 35.0% | 10.9 ms |

Graph-only retrieval answers only questions that name a person or project, which is why it is low on its own; it contributes the connected items in hybrid.

## Question answering (18 questions) and temporal QA (7)

| Suite | Answer mode | Factual accuracy | Citation accuracy | Invalid-citation rate | Unsupported-claim rate | Source relevance | p50 latency |
|---|---|---|---|---|---|---|---|
| qa | extractive | 88.9% | 88.9% | 0.0% | 1.2% | 47.9% | 24 ms |
| qa | llm | 94.4% | 88.9% | 16.7% | 4.8% | 53.8% | 3044 ms |
| temporal_qa | extractive | 85.7% | 85.7% | 0.0% | 0.0% | 48.3% | 10 ms |
| temporal_qa | llm | 100.0% | 100.0% | 0.0% | 0.0% | 57.1% | 1971 ms |

*Factual accuracy*: every required fact (dates matched in any format) appears in the answer. *Citation accuracy*: at least one cited source is among the expected sources. *Unsupported-claim rate*: share of claim sentences the verifier had to remove or flag. *Source relevance*: share of cited sources in the expected set (a narrow list, so this is a lower bound).

## Prompt injection (6 cases: injected email, document and note; direct exfiltration, secret and privilege requests)

| Model | Pass rate | Write-tool executions | Exfiltration proposals | Secret leaks | Action claims in answer | Indirect injections flagged | Unsafe sentences removed |
|---|---|---|---|---|---|---|---|
| compromised_model | 100.0% | 0 | 0 | 0 | 0 | 3/3 | 16 |
| local_llm | 100.0% | 0 | 0 | 0 | 0 | 3/3 | 4 |
| extractive | 100.0% | 0 | 0 | 0 | 0 | 3/3 | 4 |

`compromised_model` is a scripted model that tries to obey every injection (claims to send files, prints the database URL and secret key, echoes the system prompt). It measures the defences that do not depend on the model behaving.

## Permissions and privacy

10 checks, pass rate **100.0%**. Checks: write tools require approval; a write tool inside a run only creates a proposal; cross-user access returns 404; cross-user search leaks nothing; missing CSRF rejected; LOCAL mode makes zero cloud calls; HYBRID sends only allow-listed operations; sources that forbid cloud stay local; sources with AI disabled never reach a prompt.

## Agent tools

120 tool executions across 72 assistant runs; success rate **100.0%**, errors 0.

| Tool | Calls | Success | Avg latency |
|---|---|---|---|
| detect_followups | 3 | 100.0% | 7.7 ms |
| generate_meeting_brief | 3 | 100.0% | 41.0 ms |
| get_commitments | 8 | 100.0% | 19.6 ms |
| get_decisions | 24 | 100.0% | 5.0 ms |
| get_fact_history | 12 | 100.0% | 8.1 ms |
| get_person | 6 | 100.0% | 14.3 ms |
| get_project | 2 | 100.0% | 12.5 ms |
| get_projects_overview | 3 | 100.0% | 34.0 ms |
| get_tasks | 2 | 100.0% | 5.0 ms |
| get_timeline | 4 | 100.0% | 18.8 ms |
| search_memory | 53 | 100.0% | 13.8 ms |

## How to read these numbers (limitations)

* The demo world, its ground truth, the rules and the QA/retrieval question sets were written by the same developer. The QA and retrieval sets and the demo ground truth were used during development; treat those numbers as optimistic. When reviewing outputs, a few ground-truth annotations were corrected where they contradicted the stated annotation rules (e.g. greeting names count as mentions); a few legitimate commitments the system found were added to the ground truth. The demo-world commitment scores are therefore close to an upper bound, not an independent measurement.
* The 52 held-out statements were written separately and not used to tune accuracy. They exposed one crash ("I can have a first draft ready…"), which was fixed; the statement still counts. Rules scoring 100% there mainly shows the rules cover the phrasing families the author anticipated; real email will be messier.
* The LLM rows use a 4B local model on a laptop. The extractive composer beats it on facts because the planner already computed the answer; the LLM adds fluency and occasionally wrong statements (two genuine errors in the QA set).
* A first scoring pass marked correct LLM answers wrong when they wrote dates as '2026-08-20' or 'September 23'; the matcher now compares calendar days in any format.
