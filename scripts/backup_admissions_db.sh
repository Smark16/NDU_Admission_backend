#!/usr/bin/env bash
# Hourly (or daily) Postgres dump with retention — do NOT write to /tmp forever.
#
# Install on admissions-sfmis (or DB host):
#   sudo mkdir -p /var/backups/admissions_db
#   sudo chown postgres:postgres /var/backups/admissions_db
#   sudo install -m 750 -o postgres -g postgres \
#     scripts/backup_admissions_db.sh /usr/local/sbin/backup_admissions_db.sh
#
# Cron (postgres user) — every 6 hours, keep last 8 dumps (~2 days):
#   0 */6 * * * /usr/local/sbin/backup_admissions_db.sh >>/var/log/admissions_db_backup.log 2>&1
#
# Or daily at 02:15, keep last 14 days:
#   15 2 * * * KEEP=14 /usr/local/sbin/backup_admissions_db.sh >>/var/log/admissions_db_backup.log 2>&1

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/admissions_db}"
DB_NAME="${DB_NAME:-admissions_db}"
KEEP="${KEEP:-8}"
MIN_FREE_MB="${MIN_FREE_MB:-2048}"
STAMP="$(date +%Y-%m-%d_%H-%M-%S)"
OUT="${BACKUP_DIR}/${DB_NAME}_${STAMP}.dump"
TMP_OUT="${OUT}.partial"

mkdir -p "$BACKUP_DIR"

# Abort if root filesystem is critically low (avoid filling disk again).
avail_mb="$(df -Pm "$BACKUP_DIR" | awk 'NR==2 {print $4}')"
if [[ -n "$avail_mb" && "$avail_mb" -lt "$MIN_FREE_MB" ]]; then
  echo "$(date -Is) ABORT: only ${avail_mb}MB free under $BACKUP_DIR (need ${MIN_FREE_MB}MB)"
  exit 1
fi

echo "$(date -Is) Starting dump → $OUT"

# Custom format (-Fc): smaller + supports pg_restore parallel.
pg_dump -Fc --no-owner --no-acl -f "$TMP_OUT" "$DB_NAME"
mv -f "$TMP_OUT" "$OUT"

# Retention: keep newest $KEEP dumps of this DB only.
mapfile -t old < <(ls -1t "${BACKUP_DIR}/${DB_NAME}_"*.dump 2>/dev/null | tail -n +"$((KEEP + 1))" || true)
if ((${#old[@]} > 0)); then
  echo "$(date -Is) Removing ${#old[@]} old dump(s) (keeping $KEEP)"
  rm -f "${old[@]}"
fi

echo "$(date -Is) Done. Size=$(du -h "$OUT" | awk '{print $1}') Free=$(df -h "$BACKUP_DIR" | awk 'NR==2 {print $4}')"
