#!/usr/bin/env bash
set -u

ROOT="/Users/avalok/work/Q-TAIL-MVP"
LOG="$ROOT/results/openx_training_progress/update_loop.log"
mkdir -p "$(dirname "$LOG")"

while true; do
  cd "$ROOT" || exit 1
  python3 "$ROOT/tools/qtail_openx_progress_manifest.py" >> "$LOG" 2>&1
  sleep 60
done
