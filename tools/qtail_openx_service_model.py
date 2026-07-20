#!/usr/bin/env python3
"""Build a Q-Tail service delivery package calibrated by Open X training.

This is the product-facing layer after the shard-level Open X training run:
given new customer embodied-AI data, it emits a PT-heavy-tail synthetic data
plan, same-budget evaluation package, and service model card.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from qtail_build_package import build_package  # noqa: E402
from qtail_data_engine import DEFAULT_PT_SOURCE  # noqa: E402


DEFAULT_TRAINING_REPORT = ROOT / "results" / "openx_demo_training_full_demo" / "openx_demo_training_report.json"
DEFAULT_TRAINING_ROWS = ROOT / "results" / "openx_demo_training_full_demo" / "openx_shard_training_rows.csv"
DEFAULT_INPUT = ROOT / "data" / "embodied_public_anchor_real.csv"
DEFAULT_OUT = ROOT / "results" / "qtail_openx_service_public"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def to_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def quantile_buckets(rows: list[dict], bucket_count: int = 5) -> list[dict]:
    if not rows:
        return []
    scores = np.array([to_float(row.get("tail_score")) for row in rows], dtype=float)
    quantiles = np.quantile(scores, np.linspace(0, 1, bucket_count + 1))
    buckets = []
    for idx in range(bucket_count):
        lo = float(quantiles[idx])
        hi = float(quantiles[idx + 1])
        if idx == bucket_count - 1:
            mask = (scores >= lo) & (scores <= hi)
        else:
            mask = (scores >= lo) & (scores < hi)
        selected = [row for row, keep in zip(rows, mask) if keep]
        if not selected:
            continue
        source = sum(to_float(row.get("source_target")) for row in selected)
        qtail = sum(to_float(row.get("qtail_target")) for row in selected)
        source_pred = sum(to_float(row.get("source_pred")) for row in selected)
        qtail_pred = sum(to_float(row.get("qtail_pred")) for row in selected)
        buckets.append({
            "bucket": f"q{idx + 1}",
            "tail_score_min": lo,
            "tail_score_max": hi,
            "shards": len(selected),
            "source_share": source,
            "qtail_share": qtail,
            "source_pred_share": source_pred,
            "qtail_pred_share": qtail_pred,
            "target_gain_pp": (qtail - source) * 100.0,
            "predicted_gain_pp": (qtail_pred - source_pred) * 100.0,
        })
    return buckets


def dataset_priors(rows: list[dict], limit: int = 8) -> list[dict]:
    grouped: dict[str, dict[str, float]] = defaultdict(lambda: {
        "shards": 0.0,
        "bytes": 0.0,
        "source_target": 0.0,
        "qtail_target": 0.0,
        "source_pred": 0.0,
        "qtail_pred": 0.0,
        "tail_score_sum": 0.0,
    })
    for row in rows:
        item = grouped[row.get("dataset", "unknown")]
        item["shards"] += 1
        item["bytes"] += to_float(row.get("bytes"))
        item["source_target"] += to_float(row.get("source_target"))
        item["qtail_target"] += to_float(row.get("qtail_target"))
        item["source_pred"] += to_float(row.get("source_pred"))
        item["qtail_pred"] += to_float(row.get("qtail_pred"))
        item["tail_score_sum"] += to_float(row.get("tail_score"))

    priors = []
    for dataset, item in grouped.items():
        shards = max(item["shards"], 1.0)
        priors.append({
            "dataset": dataset,
            "shards": int(item["shards"]),
            "gib": item["bytes"] / (1024**3),
            "mean_tail_score": item["tail_score_sum"] / shards,
            "source_target_share": item["source_target"],
            "qtail_target_share": item["qtail_target"],
            "qtail_minus_source_pp": (item["qtail_target"] - item["source_target"]) * 100.0,
            "qtail_pred_minus_source_pred_pp": (item["qtail_pred"] - item["source_pred"]) * 100.0,
        })
    return sorted(priors, key=lambda row: row["qtail_minus_source_pp"], reverse=True)[:limit]


def build_model_card(
    training_report: dict,
    training_rows: list[dict],
    *,
    training_report_path: Path,
    training_rows_path: Path,
) -> dict:
    effect = training_report.get("effect_metrics", {})
    source_tail = float(effect.get("source_tail_share") or 0.0)
    qtail_tail = float(effect.get("qtail_tail_share") or 0.0)
    return {
        "model_name": "Q-Tail OpenX-Calibrated Data Service v0.1",
        "generated_at": now(),
        "training_source": {
            "report": str(training_report_path),
            "rows": str(training_rows_path),
            "status": training_report.get("status"),
            "steps": training_report.get("steps"),
            "datasets": training_report.get("datasets", []),
            "shard_count": training_report.get("shard_count"),
            "total_gib": training_report.get("total_gib"),
            "training_scope": training_report.get("training_scope"),
            "trajectory_evidence": training_report.get("trajectory_evidence", {}),
            "model_artifact": training_report.get("model_artifact", {}),
        },
        "learned_tail_prior": {
            "tail_definition": effect.get("tail_definition"),
            "source_tail_share": source_tail,
            "qtail_tail_share": qtail_tail,
            "target_tail_share_gain_pp": effect.get("target_tail_share_gain_pp"),
            "predicted_tail_share_gain_pp": effect.get("predicted_tail_share_gain_pp"),
            "tail_share_multiplier": qtail_tail / source_tail if source_tail > 0 else None,
            "consistent_with_pt_tail_goal": effect.get("consistent_with_pt_tail_goal"),
        },
        "tail_quantile_calibration": quantile_buckets(training_rows),
        "service_calibration": {
            "method": "customer_tail_quantile_x_openx_predicted_gain",
            "description": "Map customer task tail-score quantiles to the learned Open X quantile gain curve, then renormalize to the same synthetic budget.",
            "same_budget": True,
        },
        "dataset_priors": dataset_priors(training_rows),
        "customer_input_contract": {
            "accepted_columns": {
                "task": ["task", "task_id", "skill", "instruction", "scenario", "env"],
                "count": ["count", "episodes", "trajectories", "samples", "frequency"],
                "success": ["success", "success_rate", "reward", "score", "pass_rate"],
                "difficulty": ["difficulty", "risk", "failure_rate", "tail_score", "rarity"],
                "group": ["group", "split", "category", "bucket"],
            },
            "output": [
                "task_profiles.csv",
                "qtail_synthetic_data.csv",
                "per_task_comparison.csv",
                "qtail_data_engine_report.json",
                "qtail_service_model_card.json",
                "qtail_service_delivery_report.json",
                "README_QTAIL_DELIVERY.md",
                "qtail_delivery_package.zip",
            ],
        },
        "claim_boundary": [
            "The Open X stage trains a record-informed allocation head on real downloaded RLDS TFRecord shards.",
            "Every complete shard is covered, with a bounded number of decoded episodes per shard; this is not an all-episode policy run.",
            "The service package generates allocation/scenario specs for synthetic data production.",
            "Full robot-policy validation remains a later same-policy training run after the full RLDS/TFDS stack is ready.",
        ],
    }


def write_delivery_zip(out_dir: Path) -> Path:
    """Write a customer-facing artifact bundle for handoff."""
    zip_path = out_dir / "qtail_delivery_package.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in sorted(out_dir.rglob("*")):
            if not item.is_file() or item == zip_path:
                continue
            archive.write(item, item.relative_to(out_dir))
    return zip_path


def fmt_pct(value: object) -> str:
    number = to_float(value, default=float("nan"))
    if np.isnan(number):
        return "n/a"
    return f"{number * 100:.1f}%"


def fmt_pp(value: object) -> str:
    number = to_float(value, default=float("nan"))
    if np.isnan(number):
        return "n/a"
    sign = "+" if number >= 0 else ""
    return f"{sign}{number:.1f} pp"


def write_delivery_readme(
    *,
    out_dir: Path,
    delivery: dict,
    model_card: dict,
    evaluation_report: dict,
    training_report_path: Path,
    training_rows_path: Path,
) -> Path:
    """Write the customer/evaluator handoff README included in every package."""
    effect = delivery.get("effect_summary", {})
    decision = effect.get("decision", {})
    learned = model_card.get("learned_tail_prior", {})
    training = model_card.get("training_source", {})
    package_zip = out_dir / "qtail_delivery_package.zip"
    lines = [
        "# Q-Tail PT-Heavy-Tail Synthetic Data Delivery",
        "",
        "## What This Package Is",
        "",
        "This is a Q-Tail-for-AI delivery package for embodied-AI data teams. It takes a customer task/trajectory summary CSV, scores rare and risky tasks, then emits a PT-heavy-tail synthetic allocation plan plus a same-budget audit.",
        "",
        "The current Open X stage trains a record-informed allocation head on real downloaded Open X / RT-X RLDS TFRecord shards. Every complete shard is covered with bounded episode decoding. The final Strong run is gated until the selected add-on datasets finish downloading and pass completeness checks.",
        "",
        "## Current Evidence Summary",
        "",
        f"- Winner: {decision.get('winner', 'n/a')}",
        f"- Gate passed: {decision.get('passed', 'n/a')}",
        f"- Tail success: {fmt_pct(effect.get('source_tail_success'))} -> {fmt_pct(effect.get('qtail_tail_success'))} ({fmt_pp(effect.get('tail_success_gain_pp'))}, relative {to_float(effect.get('tail_success_relative_gain_pct'), 0.0):.1f}%)",
        f"- CVaR@20: {fmt_pct(effect.get('source_cvar20'))} -> {fmt_pct(effect.get('qtail_cvar20'))} ({fmt_pp(effect.get('cvar20_gain_pp'))})",
        f"- Tail data share: {fmt_pct(effect.get('source_tail_data_share'))} -> {fmt_pct(effect.get('qtail_tail_data_share'))} ({fmt_pp(effect.get('tail_data_share_gain_pp'))})",
        f"- Aligned with PT-heavy-tail goal: {effect.get('aligned_with_pt_tail_goal')}",
        "",
        "## Open X Calibration Source",
        "",
        f"- Training report: `{training_report_path}`",
        f"- Training rows: `{training_rows_path}`",
        f"- Status: {training.get('status', 'n/a')}",
        f"- Steps: {training.get('steps', 'n/a')}",
        f"- Downloaded data used by current snapshot: {to_float(training.get('total_gib'), 0.0):.3f} GiB",
        f"- Shards: {training.get('shard_count', 'n/a')}",
        f"- Decoded episodes: {(training.get('trajectory_evidence') or {}).get('records_decoded', 'n/a')}",
        f"- TFRecord parse coverage: {fmt_pct((training.get('trajectory_evidence') or {}).get('record_parse_rate'))}",
        f"- Model checkpoint: `{(training.get('model_artifact') or {}).get('path', 'n/a')}`",
        f"- Learned tail share prior: source {fmt_pct(learned.get('source_tail_share'))} -> Q-Tail {fmt_pct(learned.get('qtail_tail_share'))}",
        f"- Predicted tail share gain from trained allocation head: {fmt_pp(learned.get('predicted_tail_share_gain_pp'))}",
        "",
        "## Files In This Package",
        "",
        "- `task_profiles.csv`: normalized customer task profile with tail scores.",
        "- `qtail_synthetic_data.csv`: base Q-Tail synthetic allocation output.",
        "- `qtail_service_synthetic_plan.csv`: OpenX-calibrated synthetic scenario/spec plan for downstream rendering.",
        "- `per_task_comparison.csv`: same-budget source vs Q-Tail per-task comparison.",
        "- `qtail_data_engine_report.json`: machine-readable evaluation report.",
        "- `qtail_service_model_card.json`: OpenX-calibrated service model card.",
        "- `qtail_service_delivery_report.json`: delivery summary, effect metrics, claim boundary, and package paths.",
        "- `README_QTAIL_DELIVERY.md`: this handoff note.",
        f"- `qtail_delivery_package.zip`: archive containing the full package (`{package_zip}`).",
        "",
        "## How To Reproduce Locally",
        "",
        "```bash",
        "python3 tools/qtail_openx_service_model.py \\",
        "  --input data/embodied_public_anchor_real.csv \\",
        "  --out results/qtail_openx_service_public \\",
        "  --training-report results/openx_incremental_training_snapshot/openx_demo_training_report.json \\",
        "  --training-rows results/openx_incremental_training_snapshot/openx_shard_training_rows.csv \\",
        "  --allow-inconclusive",
        "",
        "python3 tools/qtail_validate_package.py results/qtail_openx_service_public/qtail_data_engine_report.json",
        "```",
        "",
        "## API Usage",
        "",
        "```bash",
        "curl -X POST http://127.0.0.1:8223/generate \\",
        "  -H 'Content-Type: application/json' \\",
        "  --data '{\"filename\":\"customer.csv\",\"csv_text\":\"task,count,success_rate,difficulty,group\\nrare_pick,12,0.32,0.91,tail\\nstandard_pick,540,0.86,0.22,head\\n\",\"synthetic_budget\":100000,\"top_k\":128}'",
        "```",
        "",
        "## Claim Boundary",
        "",
    ]
    for item in model_card.get("claim_boundary", []):
        lines.append(f"- {item}")
    lines.extend([
        "- The service package validates data allocation quality and synthetic-data targeting before expensive robot-policy retraining.",
        "- The final 20000-step Strong result will replace this incremental snapshot after download verification succeeds.",
        "",
        "## Business Use",
        "",
        "Q-Tail is useful when an embodied-AI team has enough common-case data but lacks coverage on rare, high-risk, or failure-prone tasks. The product value is that a customer can submit data summaries, receive a prioritized PT-heavy-tail synthetic data plan, and decide where to spend data-generation or robot-training budget before running full policy training.",
        "",
        f"Generated at: {delivery.get('generated_at')}",
        f"Evaluation report: `{evaluation_report.get('report_path', out_dir / 'qtail_data_engine_report.json')}`",
    ])
    readme_path = out_dir / "README_QTAIL_DELIVERY.md"
    readme_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return readme_path


def enrich_synthetic_plan(source_csv: Path, destination: Path, model_card: dict) -> None:
    rows = read_csv(source_csv)
    prior = model_card["learned_tail_prior"]
    calibration = model_card.get("tail_quantile_calibration") or []
    if not rows:
        return

    scores = np.array([to_float(row.get("tail_score")) for row in rows], dtype=float)
    order = np.argsort(np.argsort(scores, kind="stable"), kind="stable")
    quantiles = order / max(len(rows) - 1, 1)
    bucket_count = max(len(calibration), 1)
    base_shares = np.array([to_float(row.get("synthetic_share")) for row in rows], dtype=float)
    base_counts = np.array([to_float(row.get("synthetic_count")) for row in rows], dtype=float)
    total_budget = float(base_counts.sum())
    multipliers = []
    bucket_names = []
    bucket_gains = []
    for quantile in quantiles:
        bucket_index = min(int(quantile * bucket_count), bucket_count - 1)
        bucket = calibration[bucket_index] if calibration else {}
        gain_pp = to_float(bucket.get("predicted_gain_pp"), 0.0)
        multipliers.append(max(0.10, 1.0 + 2.0 * gain_pp / 100.0))
        bucket_names.append(bucket.get("bucket", f"q{bucket_index + 1}"))
        bucket_gains.append(gain_pp)
    weighted = base_shares * np.array(multipliers, dtype=float)
    calibrated_shares = weighted / max(float(weighted.sum()), 1e-12)
    calibrated_counts = calibrated_shares * total_budget
    enriched = []
    for idx, row in enumerate(rows):
        enriched.append({
            **row,
            "service_stage": "ready_for_synthetic_renderer",
            "openx_calibrated_tail_gain_pp": prior.get("predicted_tail_share_gain_pp"),
            "openx_calibration_bucket": bucket_names[idx],
            "openx_bucket_predicted_gain_pp": bucket_gains[idx],
            "openx_calibration_multiplier": multipliers[idx],
            "base_synthetic_share": base_shares[idx],
            "openx_calibrated_synthetic_share": float(calibrated_shares[idx]),
            "openx_calibrated_synthetic_count": float(calibrated_counts[idx]),
            "scenario_spec": (
                f"{row.get('task_id', 'task')} | tail_score={row.get('tail_score')} "
                f"| calibrated_share={float(calibrated_shares[idx])}"
            ),
        })
    write_csv(destination, enriched)


def build_service_package(
    *,
    input_path: Path,
    out_dir: Path,
    training_report_path: Path,
    training_rows_path: Path,
    synthetic_budget: float,
    pt_source: Path,
    top_k: int,
    require_pass: bool,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    training_report = load_json(training_report_path)
    training_rows = read_csv(training_rows_path)
    model_card = build_model_card(
        training_report,
        training_rows,
        training_report_path=training_report_path,
        training_rows_path=training_rows_path,
    )

    package = build_package(
        input_path=input_path,
        out_dir=out_dir,
        synthetic_budget=synthetic_budget,
        pt_source=pt_source,
        top_k=top_k,
        source_audit=None,
        require_pass=require_pass,
    )

    model_card_path = out_dir / "qtail_service_model_card.json"
    model_card_path.write_text(json.dumps(model_card, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    enriched_plan_path = out_dir / "qtail_service_synthetic_plan.csv"
    enrich_synthetic_plan(out_dir / "qtail_synthetic_data.csv", enriched_plan_path, model_card)

    report_path = out_dir / "qtail_data_engine_report.json"
    evaluation_report = load_json(report_path)
    gains = evaluation_report.get("evaluation", {}).get("gains", {})
    source_metrics = evaluation_report.get("evaluation", {}).get("source_data_metrics", {})
    qtail_metrics = evaluation_report.get("evaluation", {}).get("qtail_synthetic_metrics", {})
    delivery = {
        "generated_at": now(),
        "service_status": "implemented_demo_delivery",
        "input_csv": str(input_path),
        "output_dir": str(out_dir),
        "model_card": str(model_card_path),
        "synthetic_plan": str(enriched_plan_path),
        "customer_package": package,
        "service_steps": [
            {"step": "1. Ingest customer embodied data", "status": "complete", "artifact": str(out_dir / "task_profiles.csv")},
            {"step": "2. Score rarity/risk/tail profile", "status": "complete", "artifact": str(out_dir / "task_profiles.csv")},
            {"step": "3. Apply Open X trained PT-tail prior", "status": "complete", "artifact": str(model_card_path)},
            {"step": "4. Generate synthetic allocation/spec plan", "status": "complete", "artifact": str(enriched_plan_path)},
            {"step": "5. Same-budget source vs Q-Tail audit", "status": "complete", "artifact": str(report_path)},
            {"step": "6. Full policy training handoff", "status": "pending_full_policy_stack", "artifact": str(training_report_path)},
        ],
        "effect_summary": {
            "source_tail_success": source_metrics.get("tail_success"),
            "qtail_tail_success": qtail_metrics.get("tail_success"),
            "tail_success_gain_pp": (gains.get("tail_success") or 0.0) * 100.0,
            "tail_success_relative_gain_pct": (
                (gains.get("tail_success") or 0.0) / source_metrics["tail_success"] * 100.0
                if source_metrics.get("tail_success")
                else None
            ),
            "source_cvar20": source_metrics.get("cvar20"),
            "qtail_cvar20": qtail_metrics.get("cvar20"),
            "cvar20_gain_pp": (gains.get("cvar20") or 0.0) * 100.0,
            "source_tail_data_share": source_metrics.get("tail_data_share"),
            "qtail_tail_data_share": qtail_metrics.get("tail_data_share"),
            "tail_data_share_gain_pp": (gains.get("tail_data_share") or 0.0) * 100.0,
            "extreme_failure_reduction": gains.get("extreme_failure_reduction"),
            "decision": evaluation_report.get("decision", {}),
            "aligned_with_pt_tail_goal": bool(
                model_card["learned_tail_prior"].get("consistent_with_pt_tail_goal")
                and evaluation_report.get("decision", {}).get("winner") == "qtail_synthetic"
            ),
        },
        "business_use": [
            "Customer sends a task/trajectory summary CSV or RLDS export summary.",
            "Q-Tail scores rare, risky, or under-covered tasks.",
            "The Open X calibrated prior shifts generation budget toward tail tasks while preserving a source-data floor.",
            "The customer receives a synthetic data plan and audit package before expensive robot-policy retraining.",
        ],
    }
    delivery_path = out_dir / "qtail_service_delivery_report.json"
    zip_path = out_dir / "qtail_delivery_package.zip"
    readme_path = out_dir / "README_QTAIL_DELIVERY.md"
    delivery["delivery_report"] = str(delivery_path)
    delivery["readme"] = str(readme_path)
    delivery["package_zip"] = str(zip_path)
    write_delivery_readme(
        out_dir=out_dir,
        delivery=delivery,
        model_card=model_card,
        evaluation_report=evaluation_report,
        training_report_path=training_report_path,
        training_rows_path=training_rows_path,
    )
    delivery_path.write_text(json.dumps(delivery, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_delivery_zip(out_dir)
    return delivery


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an Open X calibrated Q-Tail service delivery package.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="New customer/source embodied data CSV.")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output service delivery directory.")
    parser.add_argument("--training-report", default=str(DEFAULT_TRAINING_REPORT), help="Open X training report JSON.")
    parser.add_argument("--training-rows", default=str(DEFAULT_TRAINING_ROWS), help="Open X shard training rows CSV.")
    parser.add_argument("--synthetic-budget", type=float, default=100_000.0, help="Synthetic data budget.")
    parser.add_argument("--pt-source", default=str(DEFAULT_PT_SOURCE), help="PT source CSV.")
    parser.add_argument("--top-k", type=int, default=128, help="Maximum customer task profiles.")
    parser.add_argument("--allow-inconclusive", action="store_true", help="Do not fail if the customer package gate is inconclusive.")
    args = parser.parse_args()

    delivery = build_service_package(
        input_path=Path(args.input),
        out_dir=Path(args.out),
        training_report_path=Path(args.training_report),
        training_rows_path=Path(args.training_rows),
        synthetic_budget=args.synthetic_budget,
        pt_source=Path(args.pt_source),
        top_k=args.top_k,
        require_pass=not args.allow_inconclusive,
    )
    print(json.dumps(delivery, indent=2, ensure_ascii=False))
    if not delivery["customer_package"]["validation"]["valid"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
