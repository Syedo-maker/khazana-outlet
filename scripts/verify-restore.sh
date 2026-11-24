#!/usr/bin/env bash
# Prove that a backup can be restored, not just that one was written.
#
#   bash scripts/verify-restore.sh
#
# Takes a fresh backup, restores it into a scratch database, and compares the
# two: every table's row count, and the migration version. Exits non zero on
# any difference. A backup nobody has restored is a hope, not a backup, so CI
# runs this on every push against a seeded database.
#
# Settings: DB_CONTAINER, PG_EXEC, PGUSER and PGDATABASE as in backup.sh.

set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
DB_CONTAINER="${DB_CONTAINER:-khazana-db-1}"
PG_EXEC="${PG_EXEC-docker exec -i $DB_CONTAINER}"
PGUSER="${PGUSER:-khazana}"
PGDATABASE="${PGDATABASE:-khazana}"
check_db="${PGDATABASE}_restore_check"
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

export DB_CONTAINER PG_EXEC PGUSER PGDATABASE
BACKUP_DIR="$workdir" KEEP_DAYS=0 bash "$here/backup.sh" >/dev/null
dump="$(ls "$workdir"/khazana-*.dump)"
FORCE=1 bash "$here/restore.sh" "$dump" "$check_db" >/dev/null

# One line per table: name and exact row count, for the source and the copy.
count_rows() {
  # shellcheck disable=SC2086
  $PG_EXEC psql -U "$PGUSER" -d "$1" -At -v ON_ERROR_STOP=1 <<'SQL'
SELECT format('select %L || '' '' || count(*) from %I.%I;', table_name, table_schema, table_name)
FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
ORDER BY table_name
\gexec
SQL
}

count_rows "$PGDATABASE" >"$workdir/source.txt"
count_rows "$check_db" >"$workdir/restored.txt"

tables="$(wc -l <"$workdir/source.txt" | tr -d ' ')"
rows="$(awk '{ sum += $2 } END { print sum + 0 }' "$workdir/source.txt")"

status=0
if ! diff -u "$workdir/source.txt" "$workdir/restored.txt"; then
  echo "verify-restore: the restored copy differs from the source" >&2
  status=1
fi
if [ "$tables" -lt 10 ] || [ "$rows" -lt 1 ]; then
  echo "verify-restore: only $tables tables and $rows rows, so there was nothing real to check" >&2
  status=1
fi

# shellcheck disable=SC2086
$PG_EXEC psql -U "$PGUSER" -d postgres -q -c "DROP DATABASE IF EXISTS \"$check_db\" WITH (FORCE)"

if [ "$status" -eq 0 ]; then
  echo "verify-restore: restored $tables tables and $rows rows, every count matches"
fi
exit "$status"
