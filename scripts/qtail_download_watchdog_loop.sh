#!/usr/bin/env zsh
set -euo pipefail

ROOT="/Users/avalok/work/Q-TAIL-MVP"
INTERVAL_SECONDS="${QTAIL_DOWNLOAD_WATCHDOG_INTERVAL_SECONDS:-300}"
STALE_AFTER_SECONDS="${QTAIL_DOWNLOAD_WATCHDOG_STALE_AFTER_SECONDS:-900}"
LOG="$ROOT/results/openx_strong_download/download_watchdog_loop.log"
STATUS="$ROOT/results/openx_strong_download/download_watchdog_loop_status.json"

mkdir -p "$(dirname "$LOG")"
cd "$ROOT"

while true; do
  NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  NEXT="$(date -u -v+"${INTERVAL_SECONDS}"S +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u +%Y-%m-%dT%H:%M:%SZ)"
  cat > "$STATUS" <<JSON
{
  "generated_at": "$NOW",
  "interval_seconds": $INTERVAL_SECONDS,
  "stale_after_seconds": $STALE_AFTER_SECONDS,
  "status": "checking",
  "next_check_at": "$NEXT"
}
JSON
  echo "[$NOW] watchdog check" >> "$LOG"
  python3 tools/qtail_download_watchdog.py --stale-after-seconds "$STALE_AFTER_SECONDS" >> "$LOG" 2>&1 || true
  NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  NEXT="$(date -u -v+"${INTERVAL_SECONDS}"S +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u +%Y-%m-%dT%H:%M:%SZ)"
  cat > "$STATUS" <<JSON
{
  "generated_at": "$NOW",
  "interval_seconds": $INTERVAL_SECONDS,
  "stale_after_seconds": $STALE_AFTER_SECONDS,
  "status": "sleeping",
  "next_check_at": "$NEXT"
}
JSON
  sleep "$INTERVAL_SECONDS"
done
