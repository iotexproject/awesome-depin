# Q-Tail PT-Heavy-Tail Synthetic Data Delivery

## What This Package Is

This is a Q-Tail-for-AI delivery package for embodied-AI data teams. It takes a customer task/trajectory summary CSV, scores rare and risky tasks, then emits a PT-heavy-tail synthetic allocation plan plus a same-budget audit.

The current Open X stage trains a record-informed allocation head on real downloaded Open X / RT-X RLDS TFRecord shards. Every complete shard is covered with bounded episode decoding. The final Strong run is gated until the selected add-on datasets finish downloading and pass completeness checks.

## Current Evidence Summary

- Winner: qtail_synthetic
- Gate passed: True
- Tail success: 47.8% -> 53.2% (+5.4 pp, relative 11.3%)
- CVaR@20: 45.4% -> 50.9% (+5.6 pp)
- Tail data share: 5.4% -> 39.8% (+34.4 pp)
- Aligned with PT-heavy-tail goal: True

## Open X Calibration Source

- Training report: `/Users/avalok/work/Q-TAIL-MVP/results/openx_strong_training/openx_demo_training_report.json`
- Training rows: `/Users/avalok/work/Q-TAIL-MVP/results/openx_strong_training/openx_shard_training_rows.csv`
- Status: complete
- Steps: 20000
- Downloaded data used by current snapshot: 171.622 GiB
- Shards: 562
- Decoded episodes: 2071
- TFRecord parse coverage: 100.0%
- Model checkpoint: `/Users/avalok/work/Q-TAIL-MVP/results/openx_strong_training/qtail_allocation_head.pt`
- Learned tail share prior: source 8.2% -> Q-Tail 50.1%
- Predicted tail share gain from trained allocation head: +41.8 pp

## Files In This Package

- `task_profiles.csv`: normalized customer task profile with tail scores.
- `qtail_synthetic_data.csv`: base Q-Tail synthetic allocation output.
- `qtail_service_synthetic_plan.csv`: OpenX-calibrated synthetic scenario/spec plan for downstream rendering.
- `per_task_comparison.csv`: same-budget source vs Q-Tail per-task comparison.
- `qtail_data_engine_report.json`: machine-readable evaluation report.
- `qtail_service_model_card.json`: OpenX-calibrated service model card.
- `qtail_service_delivery_report.json`: delivery summary, effect metrics, claim boundary, and package paths.
- `README_QTAIL_DELIVERY.md`: this handoff note.
- `qtail_delivery_package.zip`: archive containing the full package (`/Users/avalok/work/Q-TAIL-MVP/results/qtail_openx_service_public/qtail_delivery_package.zip`).

## How To Reproduce Locally

```bash
python3 tools/qtail_openx_service_model.py \
  --input data/embodied_public_anchor_real.csv \
  --out results/qtail_openx_service_public \
  --training-report results/openx_incremental_training_snapshot/openx_demo_training_report.json \
  --training-rows results/openx_incremental_training_snapshot/openx_shard_training_rows.csv \
  --allow-inconclusive

python3 tools/qtail_validate_package.py results/qtail_openx_service_public/qtail_data_engine_report.json
```

## API Usage

```bash
curl -X POST http://127.0.0.1:8223/generate \
  -H 'Content-Type: application/json' \
  --data '{"filename":"customer.csv","csv_text":"task,count,success_rate,difficulty,group\nrare_pick,12,0.32,0.91,tail\nstandard_pick,540,0.86,0.22,head\n","synthetic_budget":100000,"top_k":128}'
```

## Claim Boundary

- The Open X stage trains a record-informed allocation head on real downloaded RLDS TFRecord shards.
- Every complete shard is covered, with a bounded number of decoded episodes per shard; this is not an all-episode policy run.
- The service package generates allocation/scenario specs for synthetic data production.
- Full robot-policy validation remains a later same-policy training run after the full RLDS/TFDS stack is ready.
- The service package validates data allocation quality and synthetic-data targeting before expensive robot-policy retraining.
- The final 20000-step Strong result will replace this incremental snapshot after download verification succeeds.

## Business Use

Q-Tail is useful when an embodied-AI team has enough common-case data but lacks coverage on rare, high-risk, or failure-prone tasks. The product value is that a customer can submit data summaries, receive a prioritized PT-heavy-tail synthetic data plan, and decide where to spend data-generation or robot-training budget before running full policy training.

Generated at: 2026-07-10T03:08:41.353135+00:00
Evaluation report: `/Users/avalok/work/Q-TAIL-MVP/results/qtail_openx_service_public/qtail_data_engine_report.json`
