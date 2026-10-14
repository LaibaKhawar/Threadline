# ADR 0003: Rule-first extraction with optional LLM extraction
**Decision.** Deterministic extractors always run (exact spans, dates resolved against the sent time); a schema-validated LLM pass can be enabled and only adds items whose quoted span is found in the source.
**Why.** Rules are fast on CPU, reproducible and give exact provenance; LLMs add recall on unusual phrasing. Measured side by side in the evaluation report.
**Consequences.** Rules need maintenance for new phrasings; LLM extraction costs seconds per item locally.
