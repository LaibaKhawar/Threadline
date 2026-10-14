# ADR 0001: Local-first by default
**Decision.** All storage, embeddings and the default LLM run on the user's machine; cloud models are opt-in per mode, operation and source.
**Why.** The data is personal; the most reliable privacy guarantee is not sending it. A 4B local model is enough when retrieval and planning are deterministic.
**Consequences.** Answer quality is bounded by small local models; the extractive fallback keeps the product useful without any model.
