#!/usr/bin/env bash
# Back up a Threadline docker compose deployment: PostgreSQL (all data incl. graph + vectors), uploaded
# files, and configuration. Credentials inside the DB are Fernet-encrypted; the ENCRYPTION_KEY in .env is
# needed to use them after a restore, so store the .env copy somewhere safe and separate.
set -euo pipefail
DEST=${1:-backups/$(date +%Y%m%d-%H%M%S)}
mkdir -p "$DEST"
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$DEST/threadline.pgdump"
docker compose run --rm --no-deps -T --entrypoint sh backend -c 'tar -C /data -czf - uploads' > "$DEST/uploads.tgz" || true
cp .env "$DEST/env.backup" && chmod 600 "$DEST/env.backup"
echo "backup written to $DEST"
