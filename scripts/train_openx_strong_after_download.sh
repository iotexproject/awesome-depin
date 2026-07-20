#!/usr/bin/env bash
set -euo pipefail

ROOT="/Users/avalok/work/Q-TAIL-MVP"
PYTHON="/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"
LOG="$ROOT/results/openx_strong_training/train_after_download.log"
MARKER="$ROOT/results/openx_strong_training/STRONG_TRAINING_COMPLETE"
WAIT_STATUS="$ROOT/results/openx_strong_training/wait_guard_status.json"
mkdir -p "$(dirname "$LOG")"

idle_after_completion() {
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] strong pipeline already complete; idling under launchd KeepAlive" | tee -a "$LOG"
  while true; do
    sleep 3600
  done
}

if [ -f "$MARKER" ]; then
  idle_after_completion
fi

launchd_label_row() {
  local label="$1"
  launchctl list | awk -v label="$label" '$3 == label { print; exit }'
}

kickstart_downloader() {
  local uid="$1"
  local target="gui/${uid}/qtail-openx-strong-addon"
  launchctl kickstart -k "$target"
}

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] waiting for qtail-openx-strong-addon" | tee -a "$LOG"
while true; do
  cd "$ROOT" || exit 1
  "$PYTHON" "$ROOT/tools/qtail_verify_openx_strong_download.py" \
    --data-dir "$ROOT/data/openx_demo" \
    --out "$ROOT/results/openx_strong_download/strong_download_verification.json" \
    > "$ROOT/results/openx_strong_download/last_wait_verification.json"

  DOWNLOADER_ROW="$(launchd_label_row "qtail-openx-strong-addon" || true)"
  DOWNLOADER_PRESENT=false
  DOWNLOADER_PID=""
  DOWNLOADER_ACTION="downloader_running"
  KICKSTART_RETURN_CODE=""
  KICKSTART_STDOUT=""
  KICKSTART_STDERR=""
  if [ -n "$DOWNLOADER_ROW" ]; then
    DOWNLOADER_PRESENT=true
    DOWNLOADER_PID="$(printf '%s\n' "$DOWNLOADER_ROW" | awk '{print $1}')"
    if [ "$DOWNLOADER_PID" = "-" ]; then
      DOWNLOADER_PID=""
      DOWNLOADER_ACTION="downloader_loaded_without_pid"
    fi
  else
    DOWNLOADER_ACTION="downloader_label_absent"
  fi

  if [ -z "$DOWNLOADER_PID" ]; then
    UID_VALUE="$(id -u)"
    KICKSTART_STDOUT_PATH="$ROOT/results/openx_strong_training/last_downloader_kickstart.stdout"
    KICKSTART_STDERR_PATH="$ROOT/results/openx_strong_training/last_downloader_kickstart.stderr"
    if kickstart_downloader "$UID_VALUE" > "$KICKSTART_STDOUT_PATH" 2> "$KICKSTART_STDERR_PATH"; then
      KICKSTART_RETURN_CODE="0"
      DOWNLOADER_ACTION="${DOWNLOADER_ACTION}_kickstart_requested"
    else
      KICKSTART_RETURN_CODE="$?"
      DOWNLOADER_ACTION="${DOWNLOADER_ACTION}_kickstart_failed"
    fi
    KICKSTART_STDOUT="$(cat "$KICKSTART_STDOUT_PATH" 2>/dev/null || true)"
    KICKSTART_STDERR="$(cat "$KICKSTART_STDERR_PATH" 2>/dev/null || true)"
  fi

  if "$PYTHON" - "$ROOT/results/openx_strong_download/last_wait_verification.json" "$WAIT_STATUS" "$DOWNLOADER_PRESENT" "$DOWNLOADER_PID" "$DOWNLOADER_ROW" "$DOWNLOADER_ACTION" "$KICKSTART_RETURN_CODE" "$KICKSTART_STDOUT" "$KICKSTART_STDERR" <<'PY'
import json
import sys
from datetime import datetime, timezone

verification_path = sys.argv[1]
status_path = sys.argv[2]
downloader_present = sys.argv[3] == "true"
downloader_pid = sys.argv[4] or None
downloader_row = sys.argv[5] or None
downloader_action = sys.argv[6] or None
kickstart_return_code = sys.argv[7] or None
kickstart_stdout = sys.argv[8] or ""
kickstart_stderr = sys.argv[9] or ""
payload = json.load(open(verification_path, encoding="utf-8"))
ready = bool(payload.get("ready_for_strong_training"))
status = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "wait_policy": "poll_strong_download_verification_until_ready",
    "guard_command": "python3 tools/qtail_verify_openx_strong_download.py --require-ready",
    "ready_for_strong_training": ready,
    "downloader_label_present": downloader_present,
    "downloader_pid": downloader_pid,
    "downloader_launchctl_row": downloader_row,
    "downloader_action": downloader_action,
    "kickstart": {
        "requested": kickstart_return_code is not None,
        "returncode": None if kickstart_return_code is None else int(kickstart_return_code),
        "stdout": kickstart_stdout,
        "stderr": kickstart_stderr,
    },
    "verification_path": verification_path,
    "error_count": len(payload.get("errors") or []),
    "errors": payload.get("errors") or [],
}
open(status_path, "w", encoding="utf-8").write(json.dumps(status, indent=2, ensure_ascii=False) + "\n")
sys.exit(0 if ready else 1)
PY
  then
    break
  fi

  if [ -n "$DOWNLOADER_PID" ]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] strong data not ready; downloader still running" | tee -a "$LOG"
  elif [ -n "$KICKSTART_RETURN_CODE" ]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] strong data not ready; downloader not running; kickstart returncode=$KICKSTART_RETURN_CODE" | tee -a "$LOG"
  else
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] strong data not ready; downloader state=$DOWNLOADER_ACTION" | tee -a "$LOG"
  fi
  sleep 300
done

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] strong verification ready; starting strong retrain" | tee -a "$LOG"
cd "$ROOT" || exit 1
"$PYTHON" "$ROOT/tools/qtail_verify_openx_strong_download.py" \
  --data-dir "$ROOT/data/openx_demo" \
  --out "$ROOT/results/openx_strong_download/strong_download_verification.json" \
  --require-ready 2>&1 | tee -a "$LOG"
"$PYTHON" "$ROOT/tools/qtail_train_openx_demo.py" \
  --data-dir "$ROOT/data/openx_demo" \
  --out "$ROOT/results/openx_strong_training" \
  --steps 20000 \
  --records-per-shard 4 \
  --min-record-parse-rate 0.95 \
  --wait 0 \
  --min-shards 64 2>&1 | tee -a "$LOG"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] strong training finished; rebuilding public service package" | tee -a "$LOG"
"$PYTHON" "$ROOT/tools/qtail_openx_service_model.py" \
  --input data/embodied_public_anchor_real.csv \
  --out "$ROOT/results/qtail_openx_service_public" \
  --training-report "$ROOT/results/openx_strong_training/openx_demo_training_report.json" \
  --training-rows "$ROOT/results/openx_strong_training/openx_shard_training_rows.csv" \
  --top-k 128 \
  --synthetic-budget 100000 2>&1 | tee -a "$LOG"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] validating rebuilt service package" | tee -a "$LOG"
"$PYTHON" "$ROOT/tools/qtail_validate_package.py" \
  "$ROOT/results/qtail_openx_service_public/qtail_data_engine_report.json" 2>&1 | tee -a "$LOG"

date -u +%Y-%m-%dT%H:%M:%SZ > "$MARKER"
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] STRONG_TRAINING_COMPLETE $MARKER" | tee -a "$LOG"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] running post-strong MetaWorld customer API sample" | tee -a "$LOG"
"$PYTHON" "$ROOT/tools/qtail_service_client.py" \
  --input data/metaworld_benchmark_anchor.csv \
  --synthetic-budget 100000 \
  --top-k 64 \
  --out "$ROOT/results/qtail_service_api_runs/latest_metaworld_client_response.json" 2>&1 | tee -a "$LOG" || true

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] running post-strong semifinal customer API sample" | tee -a "$LOG"
"$PYTHON" "$ROOT/tools/qtail_service_client.py" \
  --input data/customer_semifinal_embodied_tasks.csv \
  --synthetic-budget 100000 \
  --top-k 64 \
  --out "$ROOT/results/qtail_service_api_runs/latest_semifinal_customer_response.json" 2>&1 | tee -a "$LOG" || true

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] validating latest post-strong customer package" | tee -a "$LOG"
"$PYTHON" - "$ROOT/results/qtail_service_api_runs/latest_semifinal_customer_response.json" <<'PY' 2>&1 | tee -a "$LOG" || true
import json
import subprocess
import sys
from pathlib import Path

response_path = Path(sys.argv[1])
payload = json.loads(response_path.read_text(encoding="utf-8"))
report = Path(payload["output_dir"]) / "qtail_data_engine_report.json"
subprocess.run([sys.executable, "tools/qtail_validate_package.py", str(report)], check=True)
PY

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] refreshing progress manifest" | tee -a "$LOG"
"$PYTHON" "$ROOT/tools/qtail_openx_progress_manifest.py" 2>&1 | tee -a "$LOG"

idle_after_completion
