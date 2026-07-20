# Gate 3 real-robot and commercial acceptance

This runbook begins only after the local Gate 1 adapter, Gate 2 controlled
simulation, and Gate 3 simulation safety package pass. It cannot be completed
with public data or Docker alone.

## Fixed acceptance protocol

1. The buyer names 3–5 production tail tasks, the robot model/serials, site,
   policy checkpoint, dataset manifest, acceptance owner, hardware-safety owner,
   and procurement owner before any trial starts.
2. Freeze baseline and Q-Tail policy hashes. Randomize or alternate the two
   conditions within each task/date so time, operator, and site changes do not
   systematically favor one condition.
3. Run at least 30 complete real-robot episodes for every task and condition on
   at least two dates. Do not delete failures, safety stops, collisions, resets,
   or operator interventions.
4. Store one immutable video/log bundle per episode and an absolute archive URL
   in `templates/gate3_real_robot_trials.csv`.
5. Record actual labor, robot, consumables, cloud, failure, and rework costs for
   both conditions in `templates/gate3_actual_cost_ledger.csv`. Every cost row
   needs an invoice or internal cost-document reference.
6. Compute CNY per successful real-robot episode. Q-Tail must reduce this unit
   effective-success cost by at least 20% while meeting the buyer's signed safety
   and policy-performance conditions.
7. The named buyer, hardware-safety owner, and procurement owner review the raw
   archive and complete a copy of `templates/gate3_buyer_signoff.example.json`.

## Automated pre-review

```bash
python3 tools/qtail_gate3_external_validator.py \
  --trials /path/to/filled_real_robot_trials.csv \
  --costs /path/to/filled_actual_cost_ledger.csv \
  --signoff /path/to/filled_buyer_signoff.json \
  --out /path/to/gate3_external_validation_report.json \
  --require-pass
```

The validator requires 3–5 tasks, at least 30 trials per task and condition,
two dates per task, valid checkpoint/manifest hashes, absolute evidence URLs,
invoice-backed cost rows, at least 20% actual unit-cost reduction, and completed
buyer/safety/procurement sign-off fields.

`ready_for_operator_review` is not buyer approval. The platform operator must
still authenticate the people, hardware logs, archive permissions, invoices,
and external contract before approving Gate 3 or marking a contract signed.
