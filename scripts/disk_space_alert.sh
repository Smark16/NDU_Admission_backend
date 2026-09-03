#!/usr/bin/env bash
# Log a warning when the root filesystem is getting full.
#
# Install:
#   sudo install -m 755 scripts/disk_space_alert.sh /usr/local/sbin/disk_space_alert.sh
#
# Root cron — every hour:
#   5 * * * * /usr/local/sbin/disk_space_alert.sh >>/var/log/disk_space_alert.log 2>&1

set -euo pipefail

THRESHOLD_PCT="${THRESHOLD_PCT:-85}"
MOUNT="${MOUNT:-/}"
used_pct="$(df -P "$MOUNT" | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"
avail="$(df -h "$MOUNT" | awk 'NR==2 {print $4}')"

if [[ -z "$used_pct" ]]; then
  echo "$(date -Is) ERROR: could not read disk usage for $MOUNT"
  exit 1
fi

if (( used_pct >= THRESHOLD_PCT )); then
  msg="$(date -Is) WARNING: $MOUNT is ${used_pct}% full (${avail} free). Check /tmp and backup jobs."
  echo "$msg"
  logger -t disk_space_alert "$msg" || true
  exit 1
fi

echo "$(date -Is) OK: $MOUNT at ${used_pct}% used (${avail} free)"
