#!/usr/bin/env bash
set -euo pipefail

ROOT="/Users/avalok/work/Q-TAIL-MVP"
LOG="$ROOT/results/qtail_auto_refresh/loop.log"
STATUS="$ROOT/results/qtail_auto_refresh/loop_status.json"
INTERVAL_SECONDS="${QTAIL_AUTO_REFRESH_INTERVAL_SECONDS:-600}"
MIN_NEW_SHARDS="${QTAIL_AUTO_REFRESH_MIN_NEW_SHARDS:-1}"
mkdir -p "$(dirname "$LOG")"

while true; do
  {
    NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "[$NOW] auto-refresh check"
    python3 - "$STATUS" "$INTERVAL_SECONDS" "$MIN_NEW_SHARDS" <<'PY'
import json
import sys
from datetime import datetime, timedelta, timezone

status_path = sys.argv[1]
interval_seconds = int(sys.argv[2])
min_new_shards = int(sys.argv[3])
now_utc = datetime.now(timezone.utc)
local_tz = timezone(timedelta(hours=8), name="Asia/Shanghai")
payload = {
    "generated_at": now_utc.isoformat(),
    "generated_at_local": now_utc.astimezone(local_tz).isoformat(),
    "loop": "qtail-auto-refresh-loop",
    "interval_seconds": interval_seconds,
    "min_new_shards": min_new_shards,
    "status": "checking",
}
open(status_path, "w", encoding="utf-8").write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
PY
    cd "$ROOT"
    python3 tools/qtail_auto_refresh.py --min-growth-gib 2 --min-new-shards "$MIN_NEW_SHARDS" --steps 2500
    python3 - "$STATUS" "$INTERVAL_SECONDS" "$MIN_NEW_SHARDS" <<'PY'
import json
import sys
from datetime import datetime, timedelta, timezone

status_path = sys.argv[1]
interval_seconds = int(sys.argv[2])
min_new_shards = int(sys.argv[3])
now_utc = datetime.now(timezone.utc)
next_utc = now_utc + timedelta(seconds=interval_seconds)
local_tz = timezone(timedelta(hours=8), name="Asia/Shanghai")
payload = {
    "generated_at": now_utc.isoformat(),
    "generated_at_local": now_utc.astimezone(local_tz).isoformat(),
    "loop": "qtail-auto-refresh-loop",
    "interval_seconds": interval_seconds,
    "min_new_shards": min_new_shards,
    "status": "sleeping",
    "next_check_after_seconds": interval_seconds,
    "next_check_at": next_utc.isoformat(),
    "next_check_at_local": next_utc.astimezone(local_tz).isoformat(),
}
open(status_path, "w", encoding="utf-8").write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
PY
  } >> "$LOG" 2>&1 || true
  sleep "$INTERVAL_SECONDS"
done
