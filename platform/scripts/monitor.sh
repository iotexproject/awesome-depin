#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-}"
COMPOSE_OVERLAYS="${COMPOSE_OVERLAYS:-}"
FAILED_JOB_LIMIT_24H="${FAILED_JOB_LIMIT_24H:-5}"
MAX_QUEUE_AGE_SECONDS="${MAX_QUEUE_AGE_SECONDS:-1800}"
MAX_WORKER_PAUSE_SECONDS="${MAX_WORKER_PAUSE_SECONDS:-1200}"

if command -v flock >/dev/null 2>&1; then
  monitor_lock="${MONITOR_LOCK_FILE:-${TMPDIR:-/tmp}/qtail-monitor-${COMPOSE_PROJECT_NAME:-default}.lock}"
  exec 9>"$monitor_lock"
  if ! flock -n 9; then
    echo "Q-Tail monitor already running; overlapping invocation skipped"
    exit 0
  fi
fi

[[ -f "$ENV_FILE" ]] || { echo "Environment file not found: $ENV_FILE" >&2; exit 1; }
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

notify_failure() {
  local message="$1"
  if [[ -n "${ALERT_WEBHOOK_URL:-}" ]]; then
    ALERT_MESSAGE="$message" python3 - <<'PY' | curl --fail --silent --show-error --max-time 15 -H 'Content-Type: application/json' --data-binary @- "$ALERT_WEBHOOK_URL" >/dev/null || true
import json, os
print(json.dumps({"service": "qtail", "severity": "critical", "message": os.environ["ALERT_MESSAGE"]}))
PY
  fi
  echo "$message" >&2
}

check_output=""
if ! check_output="$(ENV_FILE="$ENV_FILE" COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT_NAME" COMPOSE_OVERLAYS="$COMPOSE_OVERLAYS" "$ROOT_DIR/scripts/check_stack.sh" 2>&1)"; then
  notify_failure "Q-Tail stack check failed: $check_output"
  exit 2
fi
echo "$check_output"

local_url="${LOCAL_BASE_URL:-http://${WEB_BIND_HOST:-127.0.0.1}:${WEB_PORT:-8080}}"
local_url="${local_url%/}"
admin_health="$(curl --fail --silent --show-error --max-time 15 -H "X-Admin-Token: $ADMIN_TOKEN" "$local_url/api/admin/health")" || {
  notify_failure "Q-Tail protected health endpoint failed"
  exit 2
}
failed_jobs="$(ADMIN_HEALTH="$admin_health" python3 - <<'PY'
import json, os
print(int(json.loads(os.environ["ADMIN_HEALTH"])["metrics"]["jobs_failed_24h"]))
PY
)"
if (( failed_jobs > FAILED_JOB_LIMIT_24H )); then
  notify_failure "Q-Tail has $failed_jobs failed jobs in 24h (limit $FAILED_JOB_LIMIT_24H)"
  exit 2
fi
queue_state="$(ADMIN_HEALTH="$admin_health" python3 - <<'PY'
import json, os
metrics = json.loads(os.environ["ADMIN_HEALTH"])["metrics"]
print(int(metrics.get("jobs_queued") or 0), int(metrics.get("oldest_queued_seconds") or 0), int(metrics.get("worker_paused") or 0), int(metrics.get("worker_pause_age_seconds") or 0))
PY
)"
read -r queued_jobs oldest_queued_seconds worker_paused worker_pause_age_seconds <<< "$queue_state"
if (( worker_paused == 1 && worker_pause_age_seconds > MAX_WORKER_PAUSE_SECONDS )); then
  notify_failure "Q-Tail generation worker has been paused for ${worker_pause_age_seconds}s (limit $MAX_WORKER_PAUSE_SECONDS)"
  exit 2
fi
if (( worker_paused == 0 && oldest_queued_seconds > MAX_QUEUE_AGE_SECONDS )); then
  notify_failure "Q-Tail oldest queued generation is ${oldest_queued_seconds}s old (limit $MAX_QUEUE_AGE_SECONDS)"
  exit 2
fi
deletion_state="$(ADMIN_HEALTH="$admin_health" python3 - <<'PY'
import json, os
metrics = json.loads(os.environ["ADMIN_HEALTH"])["metrics"]
print(int(metrics.get("deletions_pending") or 0), int(metrics.get("deletions_overdue") or 0), int(metrics.get("retention_payloads_due") or 0))
PY
)"
read -r deletions_pending deletions_overdue retention_payloads_due <<< "$deletion_state"
if (( deletions_overdue > 0 || retention_payloads_due > 0 )); then
  notify_failure "Q-Tail data lifecycle SLA failed (deletions overdue: $deletions_overdue; retention payloads due: $retention_payloads_due)"
  exit 2
fi
echo "PASS protected operations health (failed jobs 24h: $failed_jobs; queued: $queued_jobs; oldest queue: ${oldest_queued_seconds}s; worker paused: $worker_paused; deletions pending: $deletions_pending)"
if [[ -n "${MONITOR_HEARTBEAT_URL:-}" ]]; then
  curl --fail --silent --show-error --max-time 15 "$MONITOR_HEARTBEAT_URL" >/dev/null || {
    notify_failure "Q-Tail external monitor heartbeat failed"
    exit 2
  }
  echo "PASS external monitor heartbeat"
fi
echo "Q-Tail monitoring checks passed"
