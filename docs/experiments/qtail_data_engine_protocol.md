# Q-Tail Data Engine Test Protocol

## Question

Given a user-provided embodied-AI dataset, can Q-Tail generate PT-heavy-tail synthetic allocation data that performs better than the original data distribution under the same compute budget, training-step proxy, and response model?

## Inputs

The engine accepts CSV data with any of these columns:

- Task identity: `task`, `task_id`, `skill`, `instruction`, `scenario`, `env`, `environment`, `name`, `States`
- Data mass: `count`, `n`, `episodes`, `trajectories`, `samples`, `frequency`, `Raw probabilities(%)`
- Optional observed outcome: `success`, `success_rate`, `sr`, `reward`, `score`, `pass_rate`
- Optional difficulty/risk: `difficulty`, `risk`, `failure_rate`, `tail_score`, `rarity`
- Optional group label: `group`, `split`, `category`, `bucket`

If success or difficulty is missing, the engine uses rarity-derived proxies and records that inference in the claim boundary.

## Model Steps

1. Aggregate rows into task/scenario profiles.
2. Compute `source_share`, rarity, difficulty, success proxy, and `tail_score`.
3. Load an empirical PT distribution from `data/uploaded_data.csv`; fall back to deterministic PT order statistics if unavailable.
4. Map the heaviest PT buckets to the highest `tail_score` tasks.
5. Blend `72%` PT-tail allocation with `28%` original source allocation.
6. Emit `qtail_synthetic_data.csv` with synthetic counts, shares, tail scores, and reference success.

## Same-Protocol Evaluation

Original user data and Q-Tail synthetic data are evaluated with the same response model:

- Same total synthetic budget.
- Same task profiles and baseline success.
- Same difficulty-dependent data response curve.
- Same tail definition: top `30%` of tasks by `tail_score`.

Metrics:

- Overall success
- Tail success
- CVaR@20 over worst-performing tasks
- Extreme failure count, defined as response success `< 0.40`
- Tail coverage at `0.50`
- Tail data share

## Statistical Gate

The model reports a pass/fail gate:

- Tail success gain must be at least `+2 pp`.
- CVaR@20 gain must be at least `+2 pp`.
- Tail data share gain must be at least `+10 pp`.
- Paired task-level bootstrap must satisfy `p(delta <= 0) <= 0.05` for tail success and CVaR@20.

The bootstrap uses paired source/synthetic effects per task profile. This is a distribution-quality test, not a claim that a robot policy has already been trained.

## Public Anchor Validation

The current public anchor adapter reads official public pages and creates deterministic aggregate task buckets:

- Google DeepMind Open X-Embodiment / RT-X: official aggregate metadata for cross-embodiment trajectories, robots, skills, and tasks.
- DROID: official aggregate metadata for trajectories, hours, scenes, tasks, collectors, and institutions.
- Meta AI Habitat 3.0: official qualitative benchmark tasks for social navigation and social rearrangement.
- MetaWorld local benchmark task-space anchor: static extraction of 50 V3 manipulation tasks from `Metaworld/metaworld/env_dict.py`, with ML held-out tasks treated as rare generalization tasks.

Outputs:

- `data/embodied_public_anchor_real.csv`
- `data/metaworld_benchmark_anchor.csv`
- `results/qtail_public_anchor_adapter/source_audit.json`
- `results/qtail_metaworld_anchor/source_audit.json`
- `results/qtail_data_engine_public_real/qtail_data_engine_report.json`
- `results/qtail_data_engine_metaworld/qtail_data_engine_report.json`
- `results/qtail_data_engine_public_real/qtail_synthetic_data.csv`

Each report includes:

- `decision`: machine-readable winner, pass/fail status, primary metric, decision gate, and reasons.
- `same_budget_audit`: task-set, allocation-sum, budget, response-model, tail-definition, and metric-set invariants.
- `evaluation`: source metrics, Q-Tail synthetic metrics, gains, bootstrap significance, gate results, and per-task comparisons.

Validate a package with:

```bash
python3 tools/qtail_validate_package.py results/qtail_data_engine_public_real/qtail_data_engine_report.json
python3 tools/qtail_validate_package.py results/qtail_data_engine_metaworld/qtail_data_engine_report.json
```

Build a complete customer package with:

```bash
python3 tools/qtail_build_package.py \
  --input customer.csv \
  --out results/customer_qtail_package \
  --top-k 128 \
  --synthetic-budget 100000
```

The build command writes:

- `qtail_data_engine_report.json`
- `qtail_synthetic_data.csv`
- `task_profiles.csv`
- `per_task_comparison.csv`
- `package_manifest.json`

It then runs the same validator and exits non-zero if the package fails the configured gate.

## Claim Boundary

Supported now:

- User CSV to task profiles.
- PT-heavy-tail synthetic data output.
- Same-protocol original-vs-synthetic comparison.
- Public aggregate anchor validation using Open X/RT-X, DROID, and Habitat 3.0 source metadata.
- Statistical pass/fail gate over task-level response-model effects.
- Customer-package workflow that emits report, synthetic CSV, manifest, and validator result.

Not yet supported without additional data:

- Full trajectory-level robot policy training.
- Real-world robot execution.
- Benchmark-server evaluation on private or full external datasets.
- Causal proof that PT allocation alone improves a downstream policy independent of the response-model assumptions.

## Full-Training Extension

The current Open X/RT-X and DROID anchors are official aggregate metadata adapters. They are useful for testing whether Q-Tail changes task allocation toward rare and difficult task buckets, but they are not a substitute for downloading full trajectories and training a robot policy.

A full-training validation would add these steps:

1. Download or mount the complete trajectory dataset.
2. Convert trajectories into a common task/scene/skill schema.
3. Generate Q-Tail synthetic or resampled training allocations.
4. Train the same policy architecture twice: original allocation vs Q-Tail allocation.
5. Hold compute, training steps, model, environment, and evaluation tasks fixed.
6. Report tail success, CVaR@20, extreme failure count, and rare-task coverage with the same package validator.

Current full-training runner:

```bash
python3 tools/qtail_full_training_runner.py --mode preflight --dataset both
python3 tools/qtail_full_training_runner.py --mode clone-backends --dataset both --execute
python3 tools/qtail_full_training_runner.py --mode download --dataset droid --execute
```

Current machine state:

- DROID official full-data source is `gs://gresearch/robotics/droid`.
- `gsutil du -s gs://gresearch/robotics/droid` reports `3.366 TiB`.
- This workspace currently has about `1.15 TiB` free, below the full DROID requirement plus temporary-space slack.
- `external_data/embodied_full/training_backends/droid_policy_learning` has been cloned for the DROID policy-training backend.
- A full result is not valid until the full trajectories are available and the same policy architecture has completed original-allocation and Q-Tail-allocation training under identical compute, step count, environment, and evaluator settings.
