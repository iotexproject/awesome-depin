#!/usr/bin/env bash
set -u

ROOT="/Users/avalok/work/Q-TAIL-MVP"
LOG="$ROOT/results/openx_demo_training/train_after_download.log"
mkdir -p "$(dirname "$LOG")"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] waiting for qtail-openx-demo-download" | tee -a "$LOG"
while launchctl list | grep -q "qtail-openx-demo-download"; do
  sleep 60
done

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] download job finished; starting full demo retrain" | tee -a "$LOG"
cd "$ROOT" || exit 1
exec python3 "$ROOT/tools/qtail_train_openx_demo.py" \
  --data-dir "$ROOT/data/openx_demo" \
  --out "$ROOT/results/openx_demo_training_full_demo" \
  --steps 10000 \
  --wait 0 \
  --min-shards 12
