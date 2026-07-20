#!/usr/bin/env bash
set -euo pipefail

ROOT="/Users/avalok/work/Q-TAIL-MVP"
GSUTIL="/Users/avalok/Library/Python/3.12/bin/gsutil"
OUT="$ROOT/data/openx_demo"
LOG="$ROOT/results/openx_strong_download/download.log"
VERIFY="$ROOT/results/openx_strong_download/strong_download_verification.json"
MARKER="$ROOT/results/openx_strong_download/STRONG_DOWNLOAD_COMPLETE"
GSUTIL_PROCESSES="${QTAIL_GSUTIL_PROCESSES:-1}"
GSUTIL_THREADS="${QTAIL_GSUTIL_THREADS:-16}"
GSUTIL_SLICE_THRESHOLD="${QTAIL_GSUTIL_SLICE_THRESHOLD:-256M}"
GSUTIL_SLICE_COMPONENTS="${QTAIL_GSUTIL_SLICE_COMPONENTS:-8}"
GSUTIL_OPTS=(
  -o "GSUtil:parallel_process_count=$GSUTIL_PROCESSES"
  -o "GSUtil:parallel_thread_count=$GSUTIL_THREADS"
  -o "GSUtil:sliced_object_download_threshold=$GSUTIL_SLICE_THRESHOLD"
  -o "GSUtil:sliced_object_download_max_components=$GSUTIL_SLICE_COMPONENTS"
)
MAX_ATTEMPTS="${QTAIL_STRONG_DOWNLOAD_MAX_ATTEMPTS:-0}"
RETRY_SLEEP_SECONDS="${QTAIL_STRONG_DOWNLOAD_RETRY_SLEEP_SECONDS:-120}"

mkdir -p "$OUT" "$(dirname "$LOG")"
rm -f "$MARKER"
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] gsutil_config processes=$GSUTIL_PROCESSES threads=$GSUTIL_THREADS sliced_threshold=$GSUTIL_SLICE_THRESHOLD sliced_components=$GSUTIL_SLICE_COMPONENTS" | tee -a "$LOG"

launchd_has_label() {
  local label="$1"
  launchctl list | awk -v label="$label" '$3 == label { found=1 } END { exit(found ? 0 : 1) }'
}

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] waiting for qtail-openx-demo-download" | tee -a "$LOG"
while launchd_has_label "qtail-openx-demo-download"; do
  sleep 60
done

download_one() {
  local name="$1"
  local uri="gs://gdm-robotics-open-x-embodiment/$name"
  local target="$OUT/$name"
  mkdir -p "$target"
  python3 "$ROOT/tools/qtail_verify_openx_strong_download.py" --data-dir "$OUT" --out "$VERIFY.skip_check" >/dev/null || true
  if python3 - "$name" "$VERIFY.skip_check" <<'PY'
import json
import sys

name = sys.argv[1]
path = sys.argv[2]
with open(path, "r", encoding="utf-8") as handle:
    payload = json.load(handle)
for dataset in payload.get("datasets", []):
    if dataset.get("dataset") == name and dataset.get("valid"):
        sys.exit(0)
sys.exit(1)
PY
  then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] SKIP $name already_valid" | tee -a "$LOG"
    return 0
  fi
  local attempt=0
  while true; do
    attempt=$((attempt + 1))
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] START $name attempt=$attempt $uri -> $target" | tee -a "$LOG"
    set +e
    "$GSUTIL" "${GSUTIL_OPTS[@]}" -m rsync -r "$uri" "$target" 2>&1 | tee -a "$LOG"
    local code="${PIPESTATUS[0]}"
    set -e
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] END $name attempt=$attempt code=$code" | tee -a "$LOG"
    if [[ "$code" == "0" ]]; then
      return 0
    fi
    if [[ "$MAX_ATTEMPTS" != "0" && "$attempt" -ge "$MAX_ATTEMPTS" ]]; then
      echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] FAIL $name attempts=$attempt max_attempts=$MAX_ATTEMPTS" | tee -a "$LOG"
      return "$code"
    fi
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] RETRY $name in ${RETRY_SLEEP_SECONDS}s after code=$code" | tee -a "$LOG"
    sleep "$RETRY_SLEEP_SECONDS"
  done
}

download_one "language_table"
download_one "language_table_sim"

du -sh "$OUT" | tee -a "$LOG"
python3 "$ROOT/tools/qtail_verify_openx_strong_download.py" --data-dir "$OUT" --out "$VERIFY" --require-ready | tee -a "$LOG"
date -u +%Y-%m-%dT%H:%M:%SZ > "$MARKER"
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] STRONG_DOWNLOAD_COMPLETE $MARKER" | tee -a "$LOG"
