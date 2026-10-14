# Connectors and sync

```python
class Connector:
    authenticate(); list_items(ctx); get_item(id); normalize(raw); sync(ctx); checkpoint(); revoke()
```
Connectors emit provider-neutral `NormalizedEmail | NormalizedEvent | NormalizedDocument | NormalizedNote`
or `Deletion`. Adding a source = one subclass + `@register`.

| Connector | Status | Incremental strategy |
|---|---|---|
| Local folder (PDF, DOCX, TXT, MD, CSV, XLSX, EML, MBOX, ICS) | implemented, tested; requires `LOCAL_IMPORT_ROOTS` | manifest of size+mtime per file; unchanged files not re-read; missing files → deletions |
| Gmail (read-only) | implemented, tested against mocked HTTP | History API `historyId`; 404 → bounded full resync; 429/5xx retried with backoff; token refresh |
| Google Calendar (read-only) | implemented, tested against mocked HTTP | `syncToken`; 410 → full resync; cancelled events → deletions |
| Demo workspace | implemented | full listing with content hashes |
| Outlook, Microsoft Calendar, Google Drive, Slack, Notion, GitHub, Linear | **planned** (listed in the catalog, cannot be connected) | — |

The Google connectors have **not** been run against a live Google account in this repository (that needs
OAuth client credentials); their behaviour is covered by tests with recorded-shape responses.

## Sync engine (`ingestion/sync.py`)
* Deterministic identity: unique `(user, integration, external_id)`.
* Change detection by content hash: unchanged → skipped; changed → derived data purged and rebuilt.
* Progress committed every 25 items; an interrupted sync resumes without duplicating work.
* Deletions are tombstoned (`deleted_at`) and their derived data purged via `SourceItemDeleted`.
* Errors are recorded on `sync_states` and the integration; jobs retry with exponential backoff and
  become `dead` after 3 attempts (non-retryable errors, e.g. revoked credentials, stop immediately).
* Tracks created/updated/unchanged/deleted counts, cursor, last error, rate-limit remaining.
