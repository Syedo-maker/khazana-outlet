#!/usr/bin/env bash
# Back up the database to a compressed, restorable file.
#
#   bash scripts/backup.sh                 local stack, into ./backups
#   BACKUP_DIR=/backups bash scripts/backup.sh
#
# The dump is pg_dump's custom format: compressed, and restorable table by
# table with pg_restore. It runs pg_dump inside the database container, so the
# tool version always matches the server and nothing is installed on the host.
#
# In production the backup service in docker-compose.prod.yml runs this same
# script on a schedule with PG_EXEC empty, because it already sits next to
# the database. Copying the files off the machine is the step that makes a
# backup survive losing the machine: see docs/deployment.md.
#
# Settings, all optional:
#   DB_CONTAINER    container to run pg_dump in      (khazana-db-1)
#   PG_EXEC         command prefix for pg tools      (docker exec -i $DB_CONTAINER)
#   PGUSER          database user                    (khazana)
#   PGDATABASE      database name                    (khazana)
#   BACKUP_DIR      where dumps go                   (./backups)
#   KEEP_DAYS       delete dumps older than this     (14)

set -euo pipefail

DB_CONTAINER="${DB_CONTAINER:-khazana-db-1}"
PG_EXEC="${PG_EXEC-docker exec -i $DB_CONTAINER}"
PGUSER="${PGUSER:-khazana}"
PGDATABASE="${PGDATABASE:-khazana}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"

mkdir -p "$BACKUP_DIR"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="$BACKUP_DIR/khazana-$stamp.dump"
partial="$target.partial"

# Written to a partial name first and renamed only when pg_dump succeeds, so a
# dump cut off half way is never mistaken for a good one.
# shellcheck disable=SC2086
$PG_EXEC pg_dump -U "$PGUSER" -d "$PGDATABASE" --format=custom --compress=6 --no-owner >"$partial"
mv "$partial" "$target"

bytes="$(wc -c <"$target" | tr -d ' ')"
if [ "$bytes" -lt 1024 ]; then
  echo "backup: $target is only $bytes bytes, which is not a real database" >&2
  exit 1
fi

find "$BACKUP_DIR" -name 'khazana-*.dump' -type f -mtime +"$KEEP_DAYS" -delete
echo "backup: wrote $target ($bytes bytes)"
