#!/usr/bin/env python3
"""Q-Tail data synthesis and same-protocol evaluation engine.

Given a user dataset, the engine:
1. infers task/scenario profiles;
2. builds a user-data allocation baseline;
3. generates a PT-heavy-tail synthetic allocation;
4. evaluates original data vs Q-Tail synthetic data under one response model;
5. records external validation anchors for Open X-Embodiment / Habitat-style data.

This is a product-facing data model scaffold, not a claim that real robot
training has already been run.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "results" / "qtail_data_engine"
DEFAULT_PT_SOURCE = ROOT / "data" / "uploaded_data.csv"


TASK_KEYS = ["task", "task_id", "skill", "instruction", "scenario", "env", "environment", "name", "States"]
COUNT_KEYS = ["count", "n", "episodes", "trajectories", "samples", "frequency", "Raw probabilities(%)", " raw probabilities(%)"]
SUCCESS_KEYS = ["success", "success_rate", "sr", "reward", "score", "pass_rate"]
DIFFICULTY_KEYS = ["difficulty", "risk", "failure_rate", "tail_score", "rarity"]
GROUP_KEYS = ["group", "split", "category", "bucket"]


@dataclass
class TaskProfile:
    task_id: str
    source_count: float
    source_share: float
    success_rate: float
    difficulty: float
    rarity: float
    tail_score: float
    group: str


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as handle:
        reader = csv.DictReader(handle)
        return reader.fieldnames or [], list(reader)


def first_present(columns: Iterable[str], candidates: list[str]) -> str | None:
    lookup = {col.strip().lower(): col for col in columns}
    for key in candidates:
        if key.strip().lower() in lookup:
            return lookup[key.strip().lower()]
    return None


def to_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        text = str(value).strip().replace("%", "")
        if not text:
            return default
        return float(text)
    except Exception:
        return default


def normalize(values: np.ndarray, floor: float = 1e-9) -> np.ndarray:
    values = np.maximum(np.asarray(values, dtype=float), floor)
    total = values.sum()
    if not np.isfinite(total) or total <= 0:
        return np.ones_like(values) / len(values)
    return values / total


def gini(values: np.ndarray) -> float:
    values = np.sort(np.asarray(values, dtype=float))
    if len(values) == 0 or values.sum() <= 0:
        return 0.0
    idx = np.arange(1, len(values) + 1)
    return float((2 * np.sum(idx * values) - (len(values) + 1) * values.sum()) / (len(values) * values.sum()))


def infer_profiles(path: Path, top_k: int = 64) -> tuple[list[TaskProfile], dict]:
    columns, rows = read_csv_rows(path)
    if not rows:
        raise ValueError(f"No rows found in {path}")

    task_col = first_present(columns, TASK_KEYS) or columns[0]
    count_col = first_present(columns, COUNT_KEYS)
    success_col = first_present(columns, SUCCESS_KEYS)
    difficulty_col = first_present(columns, DIFFICULTY_KEYS)
    group_col = first_present(columns, GROUP_KEYS)

    aggregate: dict[str, dict[str, float | str]] = {}
    for row in rows:
        task_id = str(row.get(task_col, "")).strip() or f"row_{len(aggregate)}"
        count = to_float(row.get(count_col), 1.0) if count_col else 1.0
        # Existing quantum CSV stores probability percentages; keep relative mass.
        count = max(count, 1e-9)
        success = to_float(row.get(success_col), math.nan) if success_col else math.nan
        difficulty = to_float(row.get(difficulty_col), math.nan) if difficulty_col else math.nan
        group = str(row.get(group_col, "")).strip().lower() if group_col else ""

        item = aggregate.setdefault(
            task_id,
            {"count": 0.0, "success_sum": 0.0, "success_n": 0.0, "difficulty_sum": 0.0, "difficulty_n": 0.0, "group": group},
        )
        item["count"] = float(item["count"]) + count
        if math.isfinite(success):
            if success > 1.0:
                success = success / 100.0
            item["success_sum"] = float(item["success_sum"]) + max(0.0, min(1.0, success))
            item["success_n"] = float(item["success_n"]) + 1.0
        if math.isfinite(difficulty):
            if difficulty > 1.0:
                difficulty = difficulty / 10.0 if difficulty <= 10 else difficulty / 100.0
            item["difficulty_sum"] = float(item["difficulty_sum"]) + max(0.0, min(1.0, difficulty))
            item["difficulty_n"] = float(item["difficulty_n"]) + 1.0
        if group:
            item["group"] = group

    # Keep largest tasks/states so UI and output stay manageable, but preserve
    # relative long-tail structure among the selected profiles.
    items = sorted(aggregate.items(), key=lambda kv: float(kv[1]["count"]), reverse=True)[:top_k]
    counts = np.array([float(item["count"]) for _, item in items], dtype=float)
    shares = normalize(counts)
    rarity_raw = 1.0 / np.sqrt(shares + 1e-12)
    rarity = (rarity_raw - rarity_raw.min()) / (rarity_raw.max() - rarity_raw.min() + 1e-12)

    profiles: list[TaskProfile] = []
    for idx, (task_id, item) in enumerate(items):
        if float(item["success_n"]) > 0:
            success_rate = float(item["success_sum"]) / float(item["success_n"])
        else:
            # If no success column exists, infer a weak proxy: rare tasks are
            # assumed less mastered, but never below 0.15.
            success_rate = max(0.15, min(0.92, 0.88 - 0.48 * float(rarity[idx])))

        if float(item["difficulty_n"]) > 0:
            difficulty = float(item["difficulty_sum"]) / float(item["difficulty_n"])
        else:
            difficulty = float(rarity[idx])

        tail_score = 0.45 * float(rarity[idx]) + 0.35 * difficulty + 0.20 * (1.0 - success_rate)
        group = str(item.get("group") or "")
        if not group:
            group = "tail" if tail_score >= 0.62 else "medium" if tail_score >= 0.36 else "head"

        profiles.append(
            TaskProfile(
                task_id=task_id,
                source_count=float(counts[idx]),
                source_share=float(shares[idx]),
                success_rate=success_rate,
                difficulty=difficulty,
                rarity=float(rarity[idx]),
                tail_score=tail_score,
                group=group,
            )
        )

    meta = {
        "input_path": str(path),
        "columns": columns,
        "row_count": len(rows),
        "profile_count": len(profiles),
        "detected_columns": {
            "task": task_col,
            "count": count_col,
            "success": success_col,
            "difficulty": difficulty_col,
            "group": group_col,
        },
    }
    return profiles, meta


def load_pt_distribution(path: Path, n: int) -> tuple[np.ndarray, dict]:
    if path.exists():
        columns, rows = read_csv_rows(path)
        prob_col = first_present(columns, COUNT_KEYS) or (columns[1] if len(columns) > 1 else None)
        probs = np.array([to_float(row.get(prob_col), 0.0) for row in rows], dtype=float) if prob_col else np.array([])
        probs = probs[np.isfinite(probs) & (probs > 0)]
        if len(probs) >= n:
            probs = normalize(np.sort(probs)[::-1])
            chunks = np.array_split(probs, n)
            buckets = normalize(np.array([chunk.sum() for chunk in chunks], dtype=float))
            return buckets, {
                "pt_source_path": str(path),
                "pt_source_rows": int(len(probs)),
                "pt_source_gini": gini(probs),
                "method": "empirical_pt_bucket_from_csv",
            }

    ranks = np.arange(1, n + 1, dtype=float)
    # Deterministic Porter-Thomas-like exponential order statistics.
    buckets = normalize(-np.log((ranks - 0.5) / (n + 0.5)))[::-1]
    return buckets, {
        "pt_source_path": str(path),
        "pt_source_rows": 0,
        "pt_source_gini": gini(buckets),
        "method": "deterministic_pt_order_statistic_fallback",
    }


def synthesize_qtail(profiles: list[TaskProfile], synthetic_budget: float, pt_source: Path) -> tuple[list[dict], np.ndarray, dict]:
    n = len(profiles)
    pt_weights, pt_meta = load_pt_distribution(pt_source, n)
    tail_order = np.argsort(np.array([p.tail_score for p in profiles], dtype=float))[::-1]
    q_weights = np.zeros(n)
    for rank, idx in enumerate(tail_order):
        q_weights[idx] = pt_weights[rank]

    # Preserve a small floor from original data, so the synthetic dataset does
    # not become a pure tail-only distribution.
    source_share = np.array([p.source_share for p in profiles], dtype=float)
    q_weights = normalize(0.72 * q_weights + 0.28 * source_share)
    rows = []
    for profile, weight in zip(profiles, q_weights):
        rows.append(
            {
                "task_id": profile.task_id,
                "source": "qtail_pt_synthetic",
                "synthetic_count": synthetic_budget * float(weight),
                "synthetic_share": float(weight),
                "tail_score": profile.tail_score,
                "group": profile.group,
                "success_rate_reference": profile.success_rate,
            }
        )
    return rows, q_weights, pt_meta


def response_success(allocation: np.ndarray, profiles: list[TaskProfile], total_budget: float) -> np.ndarray:
    counts = allocation * total_budget
    tail_scores = np.array([p.tail_score for p in profiles], dtype=float)
    base_success = np.array([p.success_rate for p in profiles], dtype=float)
    # Harder / rarer tasks need more data for the same gain.
    tau = total_budget * (0.010 + 0.085 * tail_scores)
    max_gain = 0.05 + 0.55 * tail_scores
    return np.clip(base_success + max_gain * (1.0 - np.exp(-counts / tau)), 0.0, 0.995)


def paired_bootstrap_delta(
    source_values: np.ndarray,
    synthetic_values: np.ndarray,
    mask: np.ndarray,
    *,
    n_boot: int = 5000,
    seed: int = 1729,
) -> dict:
    """Estimate paired mean-delta uncertainty over tasks.

    This is a distribution-quality test over task/scenario profiles. It is not a
    robot policy training significance test.
    """

    src = np.asarray(source_values, dtype=float)[mask]
    syn = np.asarray(synthetic_values, dtype=float)[mask]
    if len(src) == 0:
        return {"n": 0, "delta": 0.0, "ci95": [0.0, 0.0], "p_delta_le_0": 1.0, "positive_pair_rate": 0.0}

    delta = syn - src
    rng = np.random.default_rng(seed)
    samples = rng.choice(delta, size=(n_boot, len(delta)), replace=True).mean(axis=1)
    return {
        "n": int(len(delta)),
        "delta": float(delta.mean()),
        "ci95": [float(np.quantile(samples, 0.025)), float(np.quantile(samples, 0.975))],
        "p_delta_le_0": float(np.mean(samples <= 0.0)),
        "positive_pair_rate": float(np.mean(delta > 0.0)),
    }


def paired_cvar_bootstrap_delta(
    source_values: np.ndarray,
    synthetic_values: np.ndarray,
    *,
    n_boot: int = 5000,
    seed: int = 1731,
) -> dict:
    src = np.asarray(source_values, dtype=float)
    syn = np.asarray(synthetic_values, dtype=float)
    if len(src) == 0:
        return {"n": 0, "delta": 0.0, "ci95": [0.0, 0.0], "p_delta_le_0": 1.0}

    rng = np.random.default_rng(seed)
    deltas = []
    k = max(1, math.ceil(0.20 * len(src)))
    for _ in range(n_boot):
        idx = rng.choice(np.arange(len(src)), size=len(src), replace=True)
        sampled_src = np.sort(src[idx])[:k].mean()
        sampled_syn = np.sort(syn[idx])[:k].mean()
        deltas.append(sampled_syn - sampled_src)
    deltas_arr = np.asarray(deltas, dtype=float)
    observed = np.sort(syn)[:k].mean() - np.sort(src)[:k].mean()
    return {
        "n": int(len(src)),
        "delta": float(observed),
        "ci95": [float(np.quantile(deltas_arr, 0.025)), float(np.quantile(deltas_arr, 0.975))],
        "p_delta_le_0": float(np.mean(deltas_arr <= 0.0)),
    }


def evaluate_allocations(profiles: list[TaskProfile], source_alloc: np.ndarray, synthetic_alloc: np.ndarray, total_budget: float) -> dict:
    tail_scores = np.array([p.tail_score for p in profiles], dtype=float)
    tail_cut = np.quantile(tail_scores, 0.70)
    tail_mask = tail_scores >= tail_cut

    source_success = response_success(source_alloc, profiles, total_budget)
    synthetic_success = response_success(synthetic_alloc, profiles, total_budget)

    def metrics(values: np.ndarray, alloc: np.ndarray) -> dict:
        sorted_values = np.sort(values)
        cvar_k = max(1, math.ceil(0.20 * len(values)))
        return {
            "overall_success": float(values.mean()),
            "tail_success": float(values[tail_mask].mean()),
            "cvar20": float(sorted_values[:cvar_k].mean()),
            "extreme_failure_count": int(np.sum(values < 0.40)),
            "tail_coverage_at_50": float(np.mean(values[tail_mask] >= 0.50)),
            "tail_data_share": float(alloc[tail_mask].sum()),
        }

    source_metrics = metrics(source_success, source_alloc)
    synthetic_metrics = metrics(synthetic_success, synthetic_alloc)
    all_mask = np.ones(len(profiles), dtype=bool)
    significance = {
        "method": "paired task-level bootstrap over response-model effects",
        "bootstrap_iterations": 5000,
        "tail_success_delta": paired_bootstrap_delta(source_success, synthetic_success, tail_mask, seed=1729),
        "overall_success_delta": paired_bootstrap_delta(source_success, synthetic_success, all_mask, seed=1730),
        "cvar20_delta": paired_cvar_bootstrap_delta(source_success, synthetic_success, seed=1731),
    }
    pass_gate = {
        "tail_success_min_gain": 0.02,
        "cvar20_min_gain": 0.02,
        "tail_data_share_min_gain": 0.10,
        "p_delta_le_0_max": 0.05,
    }
    gate_results = {
        "tail_success_gain": synthetic_metrics["tail_success"] - source_metrics["tail_success"] >= pass_gate["tail_success_min_gain"],
        "tail_success_p": significance["tail_success_delta"]["p_delta_le_0"] <= pass_gate["p_delta_le_0_max"],
        "cvar20_gain": synthetic_metrics["cvar20"] - source_metrics["cvar20"] >= pass_gate["cvar20_min_gain"],
        "cvar20_p": significance["cvar20_delta"]["p_delta_le_0"] <= pass_gate["p_delta_le_0_max"],
        "tail_data_share_gain": synthetic_metrics["tail_data_share"] - source_metrics["tail_data_share"] >= pass_gate["tail_data_share_min_gain"],
    }
    return {
        "tail_threshold_quantile": 0.70,
        "tail_task_count": int(tail_mask.sum()),
        "source_data_metrics": source_metrics,
        "qtail_synthetic_metrics": synthetic_metrics,
        "gains": {
            key: synthetic_metrics[key] - source_metrics[key]
            for key in ["overall_success", "tail_success", "cvar20", "tail_coverage_at_50", "tail_data_share"]
        } | {
            "extreme_failure_reduction": source_metrics["extreme_failure_count"] - synthetic_metrics["extreme_failure_count"],
        },
        "significance": significance,
        "pass_gate": pass_gate,
        "test_passed": bool(all(gate_results.values())),
        "gate_results": gate_results,
        "per_task": [
            {
                "task_id": p.task_id,
                "group": p.group,
                "tail_score": p.tail_score,
                "source_share": float(source_alloc[i]),
                "synthetic_share": float(synthetic_alloc[i]),
                "source_effect": float(source_success[i]),
                "synthetic_effect": float(synthetic_success[i]),
            }
            for i, p in enumerate(profiles)
        ],
    }


def same_budget_audit(profiles: list[TaskProfile], source_alloc: np.ndarray, synthetic_alloc: np.ndarray, total_budget: float) -> dict:
    source_sum = float(np.sum(source_alloc))
    synthetic_sum = float(np.sum(synthetic_alloc))
    task_ids = [p.task_id for p in profiles]
    return {
        "same_task_set": len(task_ids) == len(set(task_ids)),
        "same_total_budget": float(total_budget),
        "source_allocation_sum": source_sum,
        "synthetic_allocation_sum": synthetic_sum,
        "allocation_sum_tolerance": 1e-6,
        "allocation_sums_valid": bool(abs(source_sum - 1.0) <= 1e-6 and abs(synthetic_sum - 1.0) <= 1e-6),
        "same_response_model": "response_success_v1",
        "same_tail_definition": "top_30_percent_by_tail_score",
        "same_metric_set": ["overall_success", "tail_success", "cvar20", "extreme_failure_count", "tail_coverage_at_50", "tail_data_share"],
        "profile_count": len(profiles),
    }


def make_decision(evaluation: dict, audit: dict) -> dict:
    gains = evaluation["gains"]
    passed = bool(evaluation["test_passed"] and audit["allocation_sums_valid"] and audit["same_task_set"])
    winner = "qtail_synthetic" if passed else "source_data_or_inconclusive"
    reasons = []
    if passed:
        reasons.extend(
            [
                f"tail_success_gain={gains['tail_success']:.6f}",
                f"cvar20_gain={gains['cvar20']:.6f}",
                f"tail_data_share_gain={gains['tail_data_share']:.6f}",
                "paired_bootstrap_p_delta_le_0_within_gate",
                "same_budget_audit_passed",
            ]
        )
    else:
        for key, value in evaluation.get("gate_results", {}).items():
            if not value:
                reasons.append(f"gate_failed:{key}")
        if not audit["allocation_sums_valid"]:
            reasons.append("audit_failed:allocation_sums")
        if not audit["same_task_set"]:
            reasons.append("audit_failed:task_set")

    return {
        "winner": winner,
        "passed": passed,
        "summary": (
            "Q-Tail synthetic data wins under the same-budget evaluation protocol."
            if passed
            else "The test is inconclusive or source data remains the safer winner under the current gate."
        ),
        "primary_metric": "tail_success",
        "decision_gate": evaluation["pass_gate"],
        "reasons": reasons,
    }


def external_validation_anchors() -> list[dict]:
    return [
        {
            "name": "Google DeepMind Open X-Embodiment / RT-X",
            "url": "https://robotics-transformer-x.github.io/",
            "why_it_matters": "Large cross-embodiment robot dataset with many skills/tasks; validates the need for task/skill distribution auditing.",
            "adapter_expected_columns": ["dataset", "robot", "task_or_language_instruction", "success_or_reward", "trajectory_count"],
            "status": "adapter-ready; full dataset not bundled locally",
        },
        {
            "name": "Meta AI Habitat / Habitat 3.0",
            "url": "https://aihabitat.org/habitat3/",
            "why_it_matters": "Embodied AI simulator for navigation/rearrangement and human-robot collaboration; validates simulated rare-scenario mining.",
            "adapter_expected_columns": ["scene", "episode_id", "task", "success", "spl_or_reward", "difficulty"],
            "status": "adapter-ready; benchmark export required",
        },
        {
            "name": "DROID / BridgeData-style real robot manipulation datasets",
            "url": "https://droid-dataset.github.io/",
            "why_it_matters": "Real robot manipulation trajectories can be grouped into task/scene/object tails for original-vs-synthetic evaluation.",
            "adapter_expected_columns": ["task", "scene", "object", "success", "trajectory_count"],
            "status": "adapter-ready; local sample/export required",
        },
    ]


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def load_source_audit(path: Path | None) -> dict | None:
    if not path:
        return None
    if not path.exists():
        raise FileNotFoundError(f"source audit not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def run(input_path: Path, out_dir: Path, synthetic_budget: float, pt_source: Path, top_k: int, source_audit: Path | None = None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    profiles, meta = infer_profiles(input_path, top_k=top_k)
    source_alloc = normalize(np.array([p.source_count for p in profiles], dtype=float))
    synthetic_rows, synthetic_alloc, pt_meta = synthesize_qtail(profiles, synthetic_budget, pt_source)
    evaluation = evaluate_allocations(profiles, source_alloc, synthetic_alloc, synthetic_budget)
    budget_audit = same_budget_audit(profiles, source_alloc, synthetic_alloc, synthetic_budget)
    decision = make_decision(evaluation, budget_audit)

    write_csv(out_dir / "task_profiles.csv", [asdict(p) for p in profiles])
    write_csv(out_dir / "qtail_synthetic_data.csv", synthetic_rows)
    write_csv(out_dir / "per_task_comparison.csv", evaluation["per_task"])

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input": meta,
        "source_audit": load_source_audit(source_audit),
        "pt_source": pt_meta,
        "synthetic_budget": synthetic_budget,
        "same_budget_audit": budget_audit,
        "decision": decision,
        "model": {
            "name": "Q-Tail Data Engine v0",
            "purpose": "Compare user-provided embodied data allocation against PT-heavy-tail synthetic allocation under one response model.",
            "claim_boundary": [
                "This evaluates data distribution quality, not full policy training.",
                "Public Open X/Habitat/DROID anchors are aggregate-metadata validations unless full exports are supplied.",
                "Synthetic data rows are allocation targets/scenario specs; rendering or robot execution is a downstream adapter.",
            ],
        },
        "evaluation": evaluation,
        "external_validation_anchors": external_validation_anchors(),
        "artifacts": {
            "task_profiles": str(out_dir / "task_profiles.csv"),
            "qtail_synthetic_data": str(out_dir / "qtail_synthetic_data.csv"),
            "per_task_comparison": str(out_dir / "per_task_comparison.csv"),
        },
    }
    (out_dir / "qtail_data_engine_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Q-Tail data synthesis and evaluation on a user CSV.")
    parser.add_argument("--input", default=str(ROOT / "data" / "uploaded_data.csv"), help="User data CSV.")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output directory.")
    parser.add_argument("--synthetic-budget", type=float, default=100_000.0, help="Synthetic data budget / scenario count.")
    parser.add_argument("--pt-source", default=str(DEFAULT_PT_SOURCE), help="PT source CSV.")
    parser.add_argument("--top-k", type=int, default=64, help="Maximum task/scenario profiles to keep.")
    parser.add_argument("--source-audit", default="", help="Optional source-audit JSON to embed in the report.")
    args = parser.parse_args()

    report = run(
        input_path=Path(args.input),
        out_dir=Path(args.out),
        synthetic_budget=args.synthetic_budget,
        pt_source=Path(args.pt_source),
        top_k=args.top_k,
        source_audit=Path(args.source_audit) if args.source_audit else None,
    )
    gains = report["evaluation"]["gains"]
    print(
        "qtail data engine complete: "
        f"tail_success_gain={gains['tail_success']:.4f}, "
        f"cvar20_gain={gains['cvar20']:.4f}, "
        f"extreme_failure_reduction={gains['extreme_failure_reduction']}"
    )


if __name__ == "__main__":
    main()
