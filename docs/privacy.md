# Privacy model

## AI modes
| Mode | Behaviour (enforced in `privacy/policy.py`, tested) |
|---|---|
| LOCAL ONLY (default) | Every LLM call goes to the local provider. Zero cloud calls regardless of other settings. |
| HYBRID | Cloud only for operations the user allow-lists **and** only when every source in the prompt allows cloud AI. Otherwise local. |
| CLOUD | The configured provider for sources that allow cloud AI; anything else stays local. |

Per source (Privacy Center): **Store locally** (off stops future syncs), **Local AI** (off: never placed in
any prompt; computed tool findings are dropped from the prompt whenever any source was withheld, and the
gateway refuses a call that names a disallowed source), **Cloud AI** (requires Local AI). Cloud calls receive
only individually permitted sources, never the computed findings. A content item whose origin cannot be
resolved is treated as disallowed for cloud. Covered by `test_findings_never_carry_text_from_a_source_with_ai_disabled`.
Embeddings are always computed locally. Every LLM call is recorded (`llm_calls`: provider, model,
locality, operation, source kinds, tokens, latency, cost).

## What stays local / what can leave
* Always local: PostgreSQL data, uploaded files, embeddings, the knowledge graph, search, audit logs.
* Can leave only with explicit settings: prompt text for allowed operations/sources in HYBRID/CLOUD mode,
  sent to the provider you configure.
* Connector traffic goes to the provider you connect (Google) using read-only scopes.
* Telemetry: none. `TELEMETRY_ENABLED` is reserved; no code path transmits usage data.

## Data controls
Export everything (zip of JSON), delete a source's imported data (including stored files), disconnect
(revokes the token upstream where supported and deletes it locally), clear AI memories, clear
conversations, delete everything (content, derived memory, people and organisations harvested from mail,
projects, corrections, proposals; the account, your own profile, connected-source settings and the audit
and LLM-call logs remain), inventory of stored records. These are good data-control practice, not a claim of legal
compliance.
