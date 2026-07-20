#!/usr/bin/env bash
set -u

ROOT="/Users/avalok/work/Q-TAIL-MVP"
GSUTIL="/Users/avalok/Library/Python/3.12/bin/gsutil"
OUT="$ROOT/data/openx_demo"
LOG="$ROOT/results/openx_demo_download/download.log"

mkdir -p "$OUT" "$(dirname "$LOG")"

download_one() {
  local name="$1"
  local uri="gs://gdm-robotics-open-x-embodiment/$name"
  local target="$OUT/$name"
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] START $name $uri -> $target" | tee -a "$LOG"
  mkdir -p "$target"
  "$GSUTIL" -m rsync -r "$uri" "$target" 2>&1 | tee -a "$LOG"
  local code="${PIPESTATUS[0]}"
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] END $name code=$code" | tee -a "$LOG"
  return "$code"
}

download_one "ucsd_kitchen_dataset_converted_externally_to_rlds"
download_one "austin_buds_dataset_converted_externally_to_rlds"
download_one "columbia_cairlab_pusht_real"
download_one "austin_sirius_dataset_converted_externally_to_rlds"
download_one "nyu_door_opening_surprising_effectiveness"
download_one "berkeley_mvp_converted_externally_to_rlds"

du -sh "$OUT" | tee -a "$LOG"
