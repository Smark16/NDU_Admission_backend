#!/usr/bin/env bash
# Local Postgres dump with retention. Primary backups live offsite — keep this light.
#
# Install on admissions-sfmis:
#   sudo mkdir -p /var/backups/admissions_db
#   sudo chown postgres:postgres /var/backups/admissions_db
#   sudo install -m 750 -o postgres -g postgres \
#     scripts/backup_admissions_db.sh /usr/local/sbin/backup_admissions_db.sh
#
# Root cron — daily at 02:15, keep 2 local dumps (remote server holds the real history):
#   15 2 * * * sudo -u postgres KEEP=2 /usr/local/sbin/backup_admissions_db.sh >>/var/log/admissions_db_backup.log 2>&1
#
# Disable the old hourly /tmp job if present:
#   # 0 */1 * * * /usr/local/bin/pg_backup.sh ...

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/admissions_db}"
DB_NAME="${DB_NAME:-admissions_db}"
KEEP="${KEEP:-2}"
MIN_FREE_MB="${MIN_FREE_MB:-2048}"
STAMP="$(date +%Y-%m-%d_%H-%M-%S)"
OUT="${BACKUP_DIR}/${DB_NAME}_${STAMP}.dump"
TMP_OUT="${OUT}.partial"

mkdir -p "$BACKUP_DIR"

# Abort if filesystem is critically low (avoid filling disk again).
avail_mb="$(df -Pm "$BACKUP_DIR" | awk 'NR==2 {print $4}')"
if [[ -n "$avail_mb" && "$avail_mb" -lt "$MIN_FREE_MB" ]]; then
  echo "$(date -Is) ABORT: only ${avail_mb}MB free under $BACKUP_DIR (need ${MIN_FREE_MB}MB)"
  exit 1
fi

echo "$(date -Is) Starting dump → $OUT"

# Custom format (-Fc): smaller + supports pg_restore parallel.
pg_dump -Fc --no-owner --no-acl -f "$TMP_OUT" "$DB_NAME"
mv -f "$TMP_OUT" "$OUT"

# Never leave legacy dumps in /tmp (that filled the disk previously).
rm -f /tmp/"${DB_NAME}_"*.dump /tmp/"${DB_NAME}_"*.dump.partial 2>/dev/null || true

# Retention: keep newest $KEEP dumps of this DB only.
mapfile -t old < <(ls -1t "${BACKUP_DIR}/${DB_NAME}_"*.dump 2>/dev/null | tail -n +"$((KEEP + 1))" || true)
if ((${#old[@]} > 0)); then
  echo "$(date -Is) Removing ${#old[@]} old dump(s) (keeping $KEEP)"
  rm -f "${old[@]}"
fi

echo "$(date -Is) Done. Size=$(du -h "$OUT" | awk '{print $1}') Free=$(df -h "$BACKUP_DIR" | awk 'NR==2 {print $4}')"
