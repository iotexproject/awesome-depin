#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-$ROOT/../.venv/bin/python}"

if [[ ! -x "$PYTHON" ]]; then
  echo "Missing Gate virtualenv: $PYTHON" >&2
  echo "Create it, install requirements-gates.txt, then install -e ../Metaworld." >&2
  exit 1
fi

cd "$ROOT"

"$PYTHON" tools/qtail_gate1_export_lerobot.py \
  --episodes 64 \
  --overwrite

"$PYTHON" tools/qtail_gate1_metaworld_synthetic.py \
  --allocation 50,7,7 \
  --overwrite \
  --require-pass

"$PYTHON" tools/qtail_gate2_metaworld_study.py \
  --baseline-allocation 60,3,1 \
  --qtail-allocation 50,7,7 \
  --qtail-lerobot-root ../results/qtail_gate1_metaworld_synthetic \
  --model-seeds 17,29,43 \
  --train-steps 5000 \
  --eval-episodes 50 \
  --overwrite \
  --require-pass

"$PYTHON" tools/qtail_gate3_simulation_validation.py \
  --episodes-per-task-per-condition 100 \
  --overwrite \
  --require-simulation-pass
