# Deployment

## Mode A: local (primary)
```bash
cp .env.example .env      # set SECRET_KEY and ENCRYPTION_KEY
docker compose up --build # postgres, redis, migrate (+demo seed), backend, worker, beat, frontend
ollama pull qwen3:4b-instruct-2507-q4_K_M   # on the host; or: docker compose --profile ollama up
```
Open http://localhost:3000. Published ports bind to 127.0.0.1 only; nothing needs a public endpoint.
To import a local folder in Docker, mount it into the `backend` and `worker` services and list the mount path in `LOCAL_IMPORT_ROOTS`.
Offline: notes, tasks, local files, search, graph, embeddings and the local model work without internet;
connector syncs and cloud models pause and the UI shows an Offline badge.

Without Docker: `make dev-db`, `make setup`, `make api`, `make web`, `make demo`.

## Mode B: self-hosted (VPS)
Differences from local:
* Put a TLS reverse proxy (Caddy/nginx) in front of the frontend; set `COOKIE_SECURE=true`, `ENVIRONMENT=production`.
* Startup refuses weak `SECRET_KEY`, empty `ENCRYPTION_KEY`, or insecure cookies.
* Set `DEMO_LOGIN_ENABLED=false` and `ALLOW_REGISTRATION=false` after creating accounts.
* Local-folder import is disabled unless `LOCAL_IMPORT_ROOTS` lists permitted server paths.
* Run Ollama on the server (GPU recommended) or accept that HYBRID/CLOUD send allowed prompts to your provider.
* Use a shared rate limiter and managed backups; keep Postgres off the public network.

## Public demo
Use only the synthetic workspace (`python -m scripts.seed_demo`). Never put real personal data in a public demo.

## Backups
```bash
./scripts/backup.sh                 # pg_dump (data, graph, vectors), uploads tarball, .env copy (chmod 600)
./scripts/restore.sh backups/<ts>
```
The graph and vectors live in PostgreSQL, so one dump captures them. Keep `ENCRYPTION_KEY` (in the
`.env` copy) separately and securely: without it stored connector credentials cannot be decrypted
(reconnecting the source fixes that; content is unaffected).
