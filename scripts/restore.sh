#!/usr/bin/env bash
# Restore a backup made by backup.sh into a running (empty or existing) compose stack.
set -euo pipefail
SRC=${1:?usage: scripts/restore.sh backups/<timestamp>}
docker compose exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' < "$SRC/threadline.pgdump"
docker compose run --rm --no-deps -T --entrypoint sh backend -c 'mkdir -p /data && tar -C /data -xzf -' < "$SRC/uploads.tgz" || true
echo "restored from $SRC (restore .env from $SRC/env.backup if this is a new machine)"
