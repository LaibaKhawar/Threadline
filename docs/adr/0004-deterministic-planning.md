# ADR 0004: Deterministic planning, LLM synthesis
**Decision.** The plan (which read tools, with which filters) is derived from the parsed question; the LLM only writes the answer from numbered sources.
**Why.** Retrieved content can never select a tool (indirect prompt injection has no path to actions), runs are reproducible, and small local models are poor planners.
**Consequences.** New question types need planner rules; unknown intents fall back to hybrid search.
