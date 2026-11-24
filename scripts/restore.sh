#!/usr/bin/env bash
# Restore a backup made by scripts/backup.sh.
#
#   bash scripts/restore.sh backups/khazana-20261123T120000Z.dump
#   bash scripts/restore.sh <dump> khazana_staging      into another database
#
# The target database is dropped and recreated, so this asks before touching
# the working database. Restoring into a scratch database first and looking at
# it is the safe way: scripts/verify-restore.sh does exactly that.
#
# Settings: DB_CONTAINER, PG_EXEC and PGUSER as in backup.sh.
# FORCE=1 skips the question, for scripts.

set -euo pipefail

dump="${1:?usage: restore.sh <dump file> [target database]}"
target_db="${2:-khazana}"
DB_CONTAINER="${DB_CONTAINER:-khazana-db-1}"
PG_EXEC="${PG_EXEC-docker exec -i $DB_CONTAINER}"
PGUSER="${PGUSER:-khazana}"

[ -s "$dump" ] || { echo "restore: $dump is missing or empty" >&2; exit 1; }

if [ "${FORCE:-0}" != "1" ]; then
  printf 'This replaces every row in database "%s". Type the database name to continue: ' "$target_db"
  read -r answer
  [ "$answer" = "$target_db" ] || { echo "Cancelled."; exit 1; }
fi

# shellcheck disable=SC2086
$PG_EXEC psql -U "$PGUSER" -d postgres -v ON_ERROR_STOP=1 -q \
  -c "SET client_min_messages = warning" \
  -c "DROP DATABASE IF EXISTS \"$target_db\" WITH (FORCE)" \
  -c "CREATE DATABASE \"$target_db\""
# shellcheck disable=SC2086
$PG_EXEC pg_restore -U "$PGUSER" -d "$target_db" --no-owner --exit-on-error <"$dump"
echo "restore: $dump restored into $target_db"
