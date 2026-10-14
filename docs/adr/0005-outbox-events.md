# ADR 0005: Transactional outbox for domain events
**Decision.** Producers write `domain_events` rows in the same transaction as their change; a dispatcher processes them in-process (single-user/local, tests) or via Celery.
**Why.** No lost or phantom events, idempotent handlers can be retried, and ingestion is decoupled from AI processing.
**Consequences.** Events are at-least-once; every handler must be idempotent (enforced with dedupe keys).
