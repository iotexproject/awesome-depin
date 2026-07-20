# Q-Tail-for-AI

**Quantum-enhanced synthetic training-data allocation for long-tail embodied intelligence**

Q-Tail-for-AI is developed by **Coherent (Beijing) Technology Co., Ltd.** The project turns a customer's task or trajectory summary into an auditable synthetic-data production plan that assigns more of a fixed budget to rare, difficult, and failure-prone embodied-AI tasks.

Q-Tail combines a Porter-Thomas heavy-tail prior, semantic risk mapping, a learned Open X allocation head, same-budget evaluation, and a delivery API. The current implementation produces task allocations and scenario specifications that can drive a simulator, renderer, human-data collection workflow, or robot execution adapter.

## What the system does

1. Ingests task or trajectory summaries in CSV, JSON, or RLDS-derived form.
2. Builds a task profile from frequency, success, difficulty, failure-risk, and instruction features.
3. Maps Porter-Thomas heavy-tail mass to high-risk task quantiles.
4. Applies an allocation head calibrated on record-level Open X evidence.
5. Emits a same-budget synthetic plan, per-task comparison, model card, manifest, and delivery package.
6. Exposes the workflow through a local private-preview API and an API-access application endpoint.

The core scheduling mixture is:

```text
q = (1 - eta) * baseline + eta * PT_prior
```

where the prior is semantically aligned so that higher probability mass is assigned to rarer or riskier tasks.

## Evidence summary

The repository separates direct training evidence from modeled evaluation evidence.

### Procurement Gate evidence (2026-07-15)

The latest buyer-readiness work adds three reproducible evidence packages without
conflating public data, simulation, and real-robot acceptance:

| Gate | Local result | Boundary |
|---|---|---|
| Gate 1 | 64 real Open X episodes converted to LeRobot v3; 1,915 frames; official loader, playback, schema, and training DataLoader passed | Public adapter baseline; buyer-specific production backend remains required |
| Gate 2 | 900 MetaWorld closed-loop evaluations; same policy and 64-trajectory budget; Tail SR +16.33 pp with paired 95% CI +12.00 to +20.67 pp | Controlled simulation; not a real-robot uplift claim |
| Gate 3 local | 3 surrogate tasks, 600 stress-test episodes, zero post-contract/non-finite/exception violations; modeled unit effective-success cost -24.02% | Real robot, site safety, invoices, buyer owner, and signed procurement acceptance remain external |

Reproduce the three local packages with:

```bash
./scripts/run_procurement_gates.sh
```

Reports are written under `../results/qtail_gate{1,2,3}_*` relative to this
repository. The Gate 3 report intentionally keeps `buyer_gate_passed` false.
When a buyer and robot are available, use
[`docs/gate3-real-robot-acceptance.md`](docs/gate3-real-robot-acceptance.md), the
three `templates/gate3_*` files, and
`tools/qtail_gate3_external_validator.py` to connect real evidence to the
existing manual-review workflow.

### Direct Open X training evidence

The strongest run processed every complete TFRecord shard in an eight-dataset Open X snapshot:

| Item | Strong run |
|---|---:|
| Local source volume | 171.622 GiB |
| Complete TFRecord shards | 562 |
| Shards parsed | 562 / 562 |
| Decoded episodes | 2,071 |
| Records per shard cap | 4 |
| Mean episode length | 127.20 steps |
| Optimization steps | 20,000 |
| Allocation-head parameters | 865 |
| Source predicted tail share | 8.25% |
| Q-Tail predicted tail share | 50.08% |
| Predicted tail-share gain | +41.83 percentage points |

The run used these Open X datasets:

- `austin_buds_dataset_converted_externally_to_rlds`
- `austin_sirius_dataset_converted_externally_to_rlds`
- `berkeley_mvp_converted_externally_to_rlds`
- `columbia_cairlab_pusht_real`
- `language_table`
- `language_table_sim`
- `nyu_door_opening_surprising_effectiveness`
- `ucsd_kitchen_dataset_converted_externally_to_rlds`

### Same-budget service evaluation

The public service package compares the source allocation with Q-Tail under the same 100,000-sample budget, the same 114 task profiles, the same response model, and the same metric definitions.

| Metric | Source | Q-Tail | Change |
|---|---:|---:|---:|
| Tail success | 47.83% | 53.24% | +5.41 pp, +11.31% relative |
| CVaR@20 | 45.38% | 50.94% | +5.56 pp |
| Tail-data share | 5.41% | 39.85% | +34.43 pp |

The registered decision gate passed and selected `qtail_synthetic` as the winner under this protocol.

Additional task-space anchors:

| Evaluation package | Profiles | Tail-success gain | CVaR@20 gain | Tail-data-share gain |
|---|---:|---:|---:|---:|
| MetaWorld benchmark anchor | 50 | +10.46 pp | +12.00 pp | +35.20 pp |
| Semifinal customer scenario sample | 10 | +35.06 pp | +39.52 pp | +36.99 pp |

The customer scenario result is a small application example and is not presented as a general benchmark.

## Recent model and training inventory

The following runs were completed during the latest development cycle.

| Run | Training scope | Volume | Shards / records | Steps | Predicted tail allocation | Artifact |
|---|---|---:|---:|---:|---:|---|
| Open X demo | shard-metadata training | 32.25 GiB | 341 shards | 3,000 | 22.33% -> 54.09% | [report](results/openx_demo_training/openx_demo_training_report.json) |
| Open X incremental | all complete shards, one decoded record per shard | 166.125 GiB | 552 / 552 | 2,500 | 8.33% -> 50.23% | [report](results/openx_incremental_training_snapshot/openx_demo_training_report.json), [checkpoint](results/openx_incremental_training_snapshot/qtail_allocation_head.pt) |
| Open X Strong | all complete shards, up to four decoded records per shard | 171.622 GiB | 562 / 2,071 | 20,000 | 8.25% -> 50.08% | [report](results/openx_strong_training/openx_demo_training_report.json), [checkpoint](results/openx_strong_training/qtail_allocation_head.pt) |
| OpenX-calibrated service model v0.1 | Strong snapshot plus customer-tail quantile calibration | 114 public task profiles | same-budget protocol | n/a | tail-data share 5.41% -> 39.85% | [model card](results/qtail_openx_service_public/qtail_service_model_card.json) |

Published checkpoint hashes:

```text
47bcc7b8beb9c0b252fd8c5323e3160310207fade4bc453006e910019b1faa7b  results/openx_incremental_training_snapshot/qtail_allocation_head.pt
7a53a2706dfc86d58e735e808987c60c72d54b94b2ca4f6520b9eeaa1445d59a  results/openx_strong_training/qtail_allocation_head.pt
```

## Product pages

Install the frontend dependencies and start the static server:

```bash
npm install
./node_modules/.bin/serve -p 54655
```

Then open:

- Main project: `http://localhost:54655/`
- Synthetic-data service: `http://localhost:54655/quantum-embodied-data-service`
- Open X training ledger: `http://localhost:54655/qtail-openx-training`
- Data engine: `http://localhost:54655/qtail-data-engine`

Run the frontend syntax checks with:

```bash
npm test
```

## Python setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run the simulation baseline:

```bash
python3 main.py --mode simulation
```

Run the Open X allocation-head trainer against an already downloaded local snapshot:

```bash
python3 tools/qtail_train_openx_demo.py --help
```

The raw Open X snapshot is intentionally not stored in this repository.

## Data-service API

Start the private-preview API:

```bash
python3 tools/qtail_service_api.py --port 8223
```

Available endpoints:

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/health` | Report service and Strong-model availability |
| `GET` | `/api-docs` | Return the machine-readable contract and claim boundary |
| `POST` | `/generate` | Convert a customer task CSV into a Q-Tail delivery package |
| `POST` | `/access-requests` | Submit a private-preview API access request |
| `GET` | `/runs` | List generated service runs |

Example:

```bash
curl -X POST http://127.0.0.1:8223/generate \
  -H 'Content-Type: application/json' \
  --data '{
    "filename": "customer_tasks.csv",
    "synthetic_budget": 100000,
    "top_k": 128,
    "csv_text": "task,count,success_rate,difficulty,group\nrare_pick,12,0.32,0.91,tail\nstandard_pick,540,0.86,0.22,head\n"
  }'
```

The generated customer package contains task profiles, a synthetic allocation plan, per-task comparisons, model and delivery reports, a manifest, and a ZIP archive.

## Reproducible artifacts

Key artifacts are committed because they are small and auditable:

- [Strong training report](results/openx_strong_training/openx_demo_training_report.json)
- [Strong training rows](results/openx_strong_training/openx_shard_training_rows.csv)
- [Strong allocation-head checkpoint](results/openx_strong_training/qtail_allocation_head.pt)
- [Public service model card](results/qtail_openx_service_public/qtail_service_model_card.json)
- [Public delivery report](results/qtail_openx_service_public/qtail_service_delivery_report.json)
- [Public package manifest](results/qtail_openx_service_public/package_manifest.json)
- [Public example delivery package](results/qtail_openx_service_public/qtail_delivery_package.zip)
- [MetaWorld task-space service report](results/qtail_service_api_runs/20260710T030841Z_metaworld_benchmark_anchor/qtail_service_delivery_report.json)
- [Semifinal scenario service report](results/qtail_service_api_runs/20260710T030841Z_customer_semifinal_embodied_tasks/qtail_service_delivery_report.json)

## Repository structure

```text
agents/       Multi-agent orchestration and specialist agents
core/         Quantum prior, semantic mapping, scheduling, and metrics
data/         Small public fixtures and quantum-run summaries only
docs/         Product, experiment, and claim-boundary documentation
experiments/  Reproducible experiment entry points
results/      Reports, figures, model cards, manifests, and small checkpoints
scripts/      Download, training, progress, and service scripts
tools/        Data engine, Open X trainer, package builder, validator, and API
```

Third-party MetaWorld and DROID policy-learning code is represented as Git submodules. Initialize it only when those backends are needed:

```bash
git submodule update --init --recursive
```

## Downloaded data policy

Downloaded robotics datasets are not committed. In particular, the local Open X data under `data/openx_demo/`, `data/openx_semifinal/`, and `data/openx_strong/` is ignored. Download logs, transient progress files, virtual environments, caches, and local API access requests are also excluded.

Reports and small trained model artifacts remain in Git so that the published claims can be inspected without the 172 GiB local dataset.

## Claim boundary

- The Strong run parsed every complete shard in the local snapshot, but decoded at most four episodes per shard. It is record-informed allocation-head training, not all-episode policy training.
- The learned artifact predicts task or shard allocation weights. It is not a robot policy checkpoint.
- The original +5.41 pp Tail SR and CVaR results come from a response-model protocol. A separate MetaWorld controlled retraining study now validates +16.33 pp closed-loop Tail SR under the same policy family and trajectory budget, but remains simulation-only.
- Current synthetic outputs are allocation targets and scenario specifications. Pixel-level rendering or robot execution is supplied by downstream adapters.
- The Open X-to-LeRobot v3 adapter is locally validated on 64 real public episodes. It does not turn every API-generated allocation plan into a customer-specific trajectory dataset.
- Gate 3 local safety and economics are simulation/model evidence. Only a buyer can supply real-robot trials, site safety approval, production invoices, and procurement signatures.
- The Porter-Thomas prior is quantum-derived or quantum-inspired. The current evidence does not establish end-to-end quantum advantage.

## Company

Q-Tail-for-AI is a research and product prototype from **Coherent (Beijing) Technology Co., Ltd.**, focused on quantum-enhanced data infrastructure for embodied intelligence.
