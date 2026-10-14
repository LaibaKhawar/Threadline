# Knowledge graph model

Nodes are references into typed tables: `person, organization, project, email, thread, event, document,
note, task, commitment, decision, topic`. Edges live in `relationships`.

| Edge | From → to | Created by |
|---|---|---|
| SENT / SENT_TO | person → email / email → person (role to/cc) | structural |
| PART_OF | email → thread | structural |
| KNOWS | person → person | structural (co-occurrence) |
| WORKS_AT | person → organization | email domain (0.6), "I've joined X" (0.8), signature (0.7) |
| PARTICIPATES_IN | person → event / project / decision | structural, inferred membership |
| BELONGS_TO | email/event/document/note/task/commitment/decision → project | project association |
| MENTIONS | source → person / organization / project | extraction (span kept) |
| COMMITTED_TO | person → commitment | extraction |
| ASSIGNED_TO | commitment → person (requests) · task → person | extraction |
| FOR | commitment → recipient | extraction |
| DEPENDS_ON | commitment → commitment ("once you've reviewed it…") | extraction |
| EXTRACTED_FROM | commitment/task → source | structural |
| FULFILLED_BY / CANCELLED_BY | commitment → source | commitment resolution (score kept) |
| DECIDED_IN | decision → source | extraction |
| SUPERSEDES | decision → decision | supersession |
| ABOUT | decision → topic | extraction |
| BLOCKED_BY | task/project → person/topic | extraction |
| REFERENCES | email → document (attachment) | structural |
| RELATED_TO | note → note (`[[backlinks]]`) | structural |
| OCCURRED_AT | event → location topic | structural |

## Time
* `valid_from` / `valid_to`: when the fact was true. `observed_at`: when Threadline learned it.
* Functional relations (`WORKS_AT`) keep one current value: a new value closes the previous edge
  (`status=superseded`, `valid_to` set) instead of overwriting it. Facts learned out of order are sorted
  by validity. Restating the same value reinforces the open period.
* `GET /api/graph/node/{type}/{id}?as_of=2026-04-01` returns the graph as it was then.

## Provenance and corrections
Edges that come from text keep `source_type`, `source_id`, `evidence_span` and `confidence`. A user can
reject an edge; rejected edges are kept as tombstones and never re-created by re-extraction.

## Why PostgreSQL rather than Neo4j
See `adr/0002-graph-in-postgres.md`.
