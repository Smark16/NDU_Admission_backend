#!/usr/bin/env bash
# Warn (log + email) when the root filesystem is getting full.
#
# Install:
#   sudo install -m 755 scripts/disk_space_alert.sh /usr/local/sbin/disk_space_alert.sh
#
# Root cron — every hour:
#   5 * * * * /usr/local/sbin/disk_space_alert.sh >>/var/log/disk_space_alert.log 2>&1
#
# Optional overrides:
#   THRESHOLD_PCT=85 ALERT_EMAILS="a@x.com b@y.com" /usr/local/sbin/disk_space_alert.sh

set -euo pipefail

THRESHOLD_PCT="${THRESHOLD_PCT:-85}"
MOUNT="${MOUNT:-/}"
ALERT_EMAILS="${ALERT_EMAILS:-jssenyange@ndejjeuniversity.ac.ug awalusimbi@ndejjeuniversity.ac.ug}"
HOST="$(hostname -f 2>/dev/null || hostname)"

used_pct="$(df -P "$MOUNT" | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"
avail="$(df -h "$MOUNT" | awk 'NR==2 {print $4}')"
used="$(df -h "$MOUNT" | awk 'NR==2 {print $3}')"
size="$(df -h "$MOUNT" | awk 'NR==2 {print $2}')"

if [[ -z "$used_pct" ]]; then
  echo "$(date -Is) ERROR: could not read disk usage for $MOUNT"
  exit 1
fi

if (( used_pct < THRESHOLD_PCT )); then
  echo "$(date -Is) OK: $MOUNT at ${used_pct}% used (${avail} free)"
  exit 0
fi

subject="[${HOST}] Disk warning: ${MOUNT} is ${used_pct}% full"
body="$(cat <<EOF
Disk space warning on ${HOST}

Mount:     ${MOUNT}
Used:      ${used_pct}% (${used} of ${size})
Available: ${avail}
Threshold: ${THRESHOLD_PCT}%
Time:      $(date -Is)

Check backup jobs and /tmp. Do not let local dumps fill the disk.
EOF
)"

echo "$(date -Is) WARNING: $MOUNT is ${used_pct}% full (${avail} free). Emailing: ${ALERT_EMAILS}"
logger -t disk_space_alert "$subject" || true

send_ok=0
if command -v mail >/dev/null 2>&1; then
  if printf '%s\n' "$body" | mail -s "$subject" $ALERT_EMAILS; then
    send_ok=1
  fi
elif command -v mailx >/dev/null 2>&1; then
  if printf '%s\n' "$body" | mailx -s "$subject" $ALERT_EMAILS; then
    send_ok=1
  fi
elif command -v sendmail >/dev/null 2>&1; then
  to_csv="$(echo "$ALERT_EMAILS" | tr ' ' ',')"
  if printf 'To: %s\nSubject: %s\n\n%s\n' "$to_csv" "$subject" "$body" | sendmail -t; then
    send_ok=1
  fi
else
  echo "$(date -Is) ERROR: no mail/mailx/sendmail installed — alert logged only"
fi

if (( send_ok == 1 )); then
  echo "$(date -Is) Email sent to: ${ALERT_EMAILS}"
else
  echo "$(date -Is) ERROR: failed to send email (check MTA / mail setup)"
fi

exit 1
