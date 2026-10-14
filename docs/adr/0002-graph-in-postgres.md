# ADR 0002: Temporal graph in PostgreSQL instead of Neo4j/Memgraph
**Decision.** Store edges in a `relationships` table (typed node references, validity interval, provenance) next to the source tables.
**Why.** One transactional store: graph edges, evidence and source rows commit together (no dual-write drift); user isolation and deletion cascade use the same mechanism as everything else; queries are 1–2 hops where indexed adjacency is fast (measured in the performance report); one fewer service for a local install and one backup.
**Trade-offs.** No Cypher, deep traversals would need recursive CTEs, no built-in graph algorithms. A read-only Neo4j projection could be added later from the same table.
