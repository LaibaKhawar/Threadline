# Security

| Area | Control |
|---|---|
| Passwords | Argon2id (`argon2-cffi`), min length 10 |
| Sessions | 256-bit random tokens, stored as SHA-256 hashes; HttpOnly, SameSite=Lax, `Secure` required in production |
| CSRF | Token = HMAC(SECRET_KEY, session); required in `x-csrf-token` on every unsafe request |
| Isolation | Personal rows carry `user_id`; by-id endpoints check ownership (404 otherwise) and every client-supplied foreign key (e.g. `project_id`) is validated against the caller. Tested through the API, including cross-user search and project attachment |
| Credentials | Connector tokens Fernet-encrypted with `ENCRYPTION_KEY`; never returned by the API; OAuth uses state + PKCE |
| Logging | Structured JSON; keys like password/token/body are redacted; bearer/API-key patterns scrubbed |
| Errors | Generic message + request id; stack traces only in server logs |
| Rate limits | Sliding window per client IP (taken from `X-Forwarded-For` set by the frontend proxy) plus a per-account login throttle: auth 10/min (`AUTH_RATE_LIMIT_PER_MINUTE`), assistant 30/min, uploads 30/min. In-process: use a shared limiter for multi-replica deployments |
| Uploads | Extension allow-list, declared-MIME check, magic-byte sniffing, size limit, NUL detection for text, zip traversal and zip-bomb checks, sanitised names, random storage names, path containment check; downloads served with `nosniff` and `CSP: sandbox` |
| Local folder import | Disabled unless `LOCAL_IMPORT_ROOTS` is set; only folders under those roots; Threadline's own data directory can never be imported; never available to the shared demo account; symlinks and hidden files skipped. Roots are server-wide, so on a multi-user server every account can import from them |
| Auth endpoints | Login, register and demo login reject cross-site `Origin` headers (login CSRF). OAuth start is a POST |
| Demo account | Shared and synthetic: uploads, integrations and OAuth are disabled for it. `DEMO_LOGIN_ENABLED` defaults to false |
| Metrics | `/metrics` answers loopback clients only |
| Headers | `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, CORS allow-list |
| Config | Startup validation refuses weak `SECRET_KEY`, missing `ENCRYPTION_KEY` or insecure cookies in production |
| Prompt injection | See `agent-runtime.md`; evaluated in the `prompt_injection` suite |
| Supply chain | `pip-audit` and `npm audit` in CI |

## Independent audit
An independent review of the code (2026-10-14) found, among others: folder import that could read any server path (including other users' uploads) through the shared demo account; tool findings that could carry text from a source with AI disabled into a prompt; unvalidated cross-user `project_id`s; re-syncs deleting user-confirmed decisions; concurrent double-processing of events; automatic resolution overriding user status changes; missing indexes; a shared rate-limit bucket behind the proxy. All of these were fixed, each with a regression test (`tests/integration/test_audit_regressions.py`, plus connector tests). Remaining items are listed below and in the final engineering report.

## Remaining risks
* The in-process rate limiter does not coordinate across replicas.
* Rule-based injection detection is pattern-based; a novel phrasing is still only data (no tool path),
  but may not be flagged in the UI.
* A local LLM can still produce a wrong but cited answer; citations are checked for existence and dates,
  not full semantic entailment.
* The demo login (`DEMO_LOGIN_ENABLED`) must be off for any deployment holding real data.
* `LOCAL_IMPORT_ROOTS` is server-wide, not per user.
* A person who "left" an organisation can be shown as current again if older mail from that organisation is processed later (the temporal reorder does not keep an explicit end marker).
* Several list endpoints still issue per-row queries (N+1) and some processing steps scan a user's open commitments/tasks; fine at personal scale (see the performance report), not tuned for very large mailboxes.
