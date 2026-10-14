# Agent runtime

`backend/app/agent/runtime.py` runs a fixed loop and records each phase in `agent_steps` as a
structured summary of actions (never model reasoning):

| Phase | What happens |
|---|---|
| PLAN | The question is parsed (people, projects, organisations, types, time range, intents). A deterministic planner maps intents to read tools, e.g. *waiting on* → `get_commitments(actor, open/overdue)`, *prepare* → `generate_meeting_brief`, *superseded* → `get_decisions(status)`, deadlines → `get_fact_history`. `search_memory` (hybrid) is added for supporting evidence. |
| EXECUTE | Each tool runs under its declared permission. Read tools are user-scoped queries. Write tools never execute inside a run: they become `action_proposals`. |
| OBSERVE | Sources are collected and de-duplicated; sources with instruction-like text are flagged. |
| REVISE | If fewer than two sources were found, one broadened search runs (no time filter). If the model is unavailable, the run switches to the extractive composer. |
| VERIFY | Citations must reference provided sources; uncited factual sentences are removed; dates must appear in a cited source or computed finding (otherwise flagged); secret-shaped strings and configured secret values are redacted; sentences that claim actions or echo injected instructions or the system prompt are dropped. |
| ANSWER | Answer, citations, verification stats and steps are stored on the run. |

## Tool permissions
Every tool declares access (READ/WRITE), scope, sensitivity and whether approval is required.
Registering a write tool without approval raises at import time.

| Tool | Access | Scope | Approval |
|---|---|---|---|
| search_memory, search_email, search_documents, search_calendar | READ | all / email / files / calendar | no |
| get_commitments, get_tasks, get_decisions, get_fact_history, get_timeline | READ | commitments / tasks / decisions / memory | no |
| get_project, get_projects_overview, get_person, find_related_entities | READ | projects / people / graph | no |
| retrieve_source (high sensitivity), generate_meeting_brief, detect_followups | READ | all / calendar / memory | no |
| draft_email, send_email, create_task, delete_document, modify_calendar | WRITE | email / tasks / files / calendar | **yes** |

Approving a proposal executes only what can be done locally (e.g. create a task). Email sending is not
implemented: connectors request read-only scopes, so an approved draft is recorded for the user to send.

## Prompt-injection defence (layers)
1. Tool selection never depends on retrieved content (deterministic planner).
2. Retrieved text is fenced as untrusted data and flagged when it contains instruction-like text.
3. The assistant has no write capability; write tools only create proposals; bulk exports from chat are refused.
4. Output guard in the verifier (action claims, injected instructions, system-prompt echoes, secrets).
Results are in the evaluation report (`prompt_injection` suite, including a deliberately compromised model).

## Working memory
Follow-up questions in a conversation inherit the previous person/intent when they name none
("and what about Phoenix?"). The last two answers are included in the prompt.
