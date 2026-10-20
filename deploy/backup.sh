#!/usr/bin/env bash
# Daily backup of the game database: a compressed copy kept for 14 days and,
# if FIELDHAND_BACKUP_URL is set, uploaded there (an object storage URL that
# only allows writes, such as an Oracle pre-authenticated request).
set -euo pipefail
# The database holds the players' tokens: backups are readable by this user only.
umask 077

DB="${FIELDHAND_DB:-/var/lib/fieldhand/fieldhand.db}"
DIR="$(dirname "$DB")/backups"
NAME="fieldhand-$(date -u +%Y%m%d-%H%M%S).db.gz"
KEEP=14
PYTHON="${FIELDHAND_PYTHON:-/opt/fieldhand/.venv/bin/python}"

mkdir -p "$DIR"
# SQLite's online backup gives a consistent copy while the server keeps running.
"$PYTHON" - "$DB" "$DIR/next.db" <<'PY'
import sqlite3, sys
src, dst = sqlite3.connect(sys.argv[1]), sqlite3.connect(sys.argv[2])
src.backup(dst)
dst.close()
PY
gzip -c "$DIR/next.db" > "$DIR/$NAME"
rm "$DIR/next.db"
ls -1t "$DIR"/fieldhand-*.db.gz | tail -n +$((KEEP + 1)) | xargs -r rm --

if [ -n "${FIELDHAND_BACKUP_URL:-}" ]; then
  curl -fsS --retry 3 -T "$DIR/$NAME" "${FIELDHAND_BACKUP_URL}${NAME}"
fi
echo "backup $NAME done"
