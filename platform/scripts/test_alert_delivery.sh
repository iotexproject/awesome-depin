#!/usr/bin/env bash
set -Eeuo pipefail

OPERATIONS_ENV_FILE="${OPERATIONS_ENV_FILE:-}"
if [[ -n "$OPERATIONS_ENV_FILE" ]]; then
  [[ -f "$OPERATIONS_ENV_FILE" ]] || { echo "Operations environment not found: $OPERATIONS_ENV_FILE" >&2; exit 2; }
  set -a
  # shellcheck disable=SC1090
  source "$OPERATIONS_ENV_FILE"
  set +a
fi

[[ "${ALERT_WEBHOOK_URL:-}" == https://* ]] || {
  echo "ALERT_WEBHOOK_URL must be a configured HTTPS URL" >&2
  exit 2
}

run_id="$(date -u +%Y%m%dT%H%M%SZ)-alert-test"
ALERT_TEST_RUN_ID="$run_id" python3 - <<'PY' | \
  curl --fail --silent --show-error --max-time 15 \
    -H 'Content-Type: application/json' --data-binary @- "$ALERT_WEBHOOK_URL" >/dev/null
import json
import os

print(json.dumps({
    "service": "qtail",
    "severity": "test",
    "test": True,
    "run_id": os.environ["ALERT_TEST_RUN_ID"],
    "message": "Q-Tail external alert delivery acceptance test",
}))
PY

if [[ -n "${MONITOR_HEARTBEAT_URL:-}" ]]; then
  [[ "$MONITOR_HEARTBEAT_URL" == https://* ]] || {
    echo "MONITOR_HEARTBEAT_URL must be HTTPS" >&2
    exit 2
  }
  curl --fail --silent --show-error --max-time 15 "$MONITOR_HEARTBEAT_URL" >/dev/null
fi

echo "PASS external alert delivery"
echo "Run ID: $run_id"
