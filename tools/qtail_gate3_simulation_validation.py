#!/usr/bin/env python3
"""Build the locally verifiable portion of Q-Tail Gate 3.

This script deliberately stops short of claiming buyer or real-robot approval.
It runs a three-task MetaWorld safety/stress campaign, derives a transparent
simulation-equivalent cost model from the controlled Gate 2 experiment, and
writes the remaining external acceptance items as explicit failures.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import shutil
from datetime import UTC, datetime
from pathlib import Path

import gymnasium as gym
import metaworld
import mujoco
import numpy as np
from metaworld.policies import ENV_POLICY_MAP


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GATE2_REPORT = ROOT.parent / "results" / "qtail_gate2_metaworld_controlled" / "gate2_acceptance_report.json"
DEFAULT_OUT = ROOT.parent / "results" / "qtail_gate3_simulation_validation"
TASKS = ("door-open-v3", "drawer-open-v3", "push-v3")
CONDITIONS = {
    "reference_nominal": 0.0,
    "reference_action_perturbation": 0.02,
}


def now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def create_env(task: str, seed: int):
    return gym.make(
        "Meta-World/MT1",
        env_name=task,
        seed=seed,
        disable_env_checker=True,
    )


def run_simulation_campaign(*, episodes: int, max_steps: int, base_seed: int) -> tuple[list[dict], list[dict]]:
    episode_rows: list[dict] = []
    task_rows: list[dict] = []
    for condition_index, (condition, action_noise) in enumerate(CONDITIONS.items()):
        for task_index, task in enumerate(TASKS):
            env_seed = base_seed + condition_index * 1_000_000 + task_index * 100_000
            env = create_env(task, env_seed)
            policy = ENV_POLICY_MAP[task]()
            task_episode_rows: list[dict] = []
            for episode_index in range(episodes):
                episode_seed = env_seed + episode_index
                rng = np.random.default_rng(episode_seed)
                exception = ""
                success = False
                terminated_early = False
                episode_return = 0.0
                action_steps = 0
                raw_saturation_steps = 0
                post_clip_bounds_violations = 0
                nonfinite_observation_steps = 0
                nonfinite_action_steps = 0
                nonfinite_reward_steps = 0
                try:
                    observation, _ = env.reset(seed=episode_seed)
                    for step in range(max_steps):
                        if not np.isfinite(observation).all():
                            nonfinite_observation_steps += 1
                        raw_action = np.asarray(policy.get_action(observation), dtype=np.float64)
                        if action_noise:
                            raw_action = raw_action + rng.normal(0.0, action_noise, size=raw_action.shape)
                        if not np.isfinite(raw_action).all():
                            nonfinite_action_steps += 1
                        raw_saturation_steps += int(bool(np.any(np.abs(raw_action) > 1.0)))
                        action = np.clip(raw_action, -1.0, 1.0).astype(np.float32)
                        post_clip_bounds_violations += int(bool(np.any(np.abs(action) > 1.0)))
                        observation, reward, terminated, truncated, info = env.step(action)
                        if not np.isfinite(reward):
                            nonfinite_reward_steps += 1
                        episode_return += float(reward)
                        success = success or bool(info.get("success"))
                        action_steps = step + 1
                        if success or terminated or truncated:
                            terminated_early = bool(terminated or truncated) and not success
                            break
                except Exception as error:  # retain simulator failures in the evidence log
                    exception = f"{type(error).__name__}: {error}"
                row = {
                    "condition": condition,
                    "task": task,
                    "episode_index": episode_index,
                    "episode_seed": episode_seed,
                    "success": int(success),
                    "return": episode_return,
                    "length": action_steps,
                    "terminated_without_success": int(terminated_early),
                    "raw_saturation_steps": raw_saturation_steps,
                    "post_clip_bounds_violations": post_clip_bounds_violations,
                    "nonfinite_observation_steps": nonfinite_observation_steps,
                    "nonfinite_action_steps": nonfinite_action_steps,
                    "nonfinite_reward_steps": nonfinite_reward_steps,
                    "exception": exception,
                }
                episode_rows.append(row)
                task_episode_rows.append(row)
            env.close()
            task_rows.append({
                "condition": condition,
                "task": task,
                "episodes": len(task_episode_rows),
                "successes": sum(row["success"] for row in task_episode_rows),
                "success_rate": float(np.mean([row["success"] for row in task_episode_rows])),
                "mean_length": float(np.mean([row["length"] for row in task_episode_rows])),
                "raw_saturation_steps": sum(row["raw_saturation_steps"] for row in task_episode_rows),
                "post_clip_bounds_violations": sum(row["post_clip_bounds_violations"] for row in task_episode_rows),
                "nonfinite_steps": sum(
                    row["nonfinite_observation_steps"] + row["nonfinite_action_steps"] + row["nonfinite_reward_steps"]
                    for row in task_episode_rows
                ),
                "exceptions": sum(bool(row["exception"]) for row in task_episode_rows),
            })
    return episode_rows, task_rows


def build_cost_model(gate2_report: dict) -> dict:
    metrics = gate2_report["metrics"]
    budget = float(metrics["trajectory_budget_per_condition"])
    baseline_rate = float(metrics["rates"]["baseline"]["tail_success_rate"])
    qtail_rate = float(metrics["rates"]["qtail"]["tail_success_rate"])
    if baseline_rate <= 0 or qtail_rate <= 0:
        raise RuntimeError("Gate 2 tail success rates must be positive for the cost model")
    baseline_cost = budget / baseline_rate
    qtail_cost = budget / qtail_rate
    reduction = (baseline_cost - qtail_cost) / baseline_cost * 100.0
    return {
        "model": "same-budget simulation-equivalent trajectory cost per expected successful tail rollout",
        "currency": "normalized trajectory-cost units; not CNY and not supplier invoices",
        "training_trajectory_budget_per_condition": budget,
        "baseline_tail_success_rate": baseline_rate,
        "qtail_tail_success_rate": qtail_rate,
        "baseline_unit_effective_success_cost": baseline_cost,
        "qtail_unit_effective_success_cost": qtail_cost,
        "unit_cost_reduction_pct": reduction,
        "threshold_pct": 20.0,
        "threshold_passed": reduction >= 20.0,
        "claim_boundary": "Modeled from controlled MetaWorld results; production labor, hardware, cloud, and rework invoices remain externally unverified.",
    }


def build_manifest(out: Path) -> tuple[Path, str]:
    files = sorted(path for path in out.rglob("*") if path.is_file() and path.name not in {"artifact_manifest.json", "gate3_acceptance_report.json"})
    entries = [
        {"path": str(path.relative_to(out)), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
        for path in files
    ]
    manifest_path = out / "artifact_manifest.json"
    manifest_path.write_text(json.dumps({
        "generated_at": now(),
        "experiment": "qtail_gate3_local_simulation_safety_and_cost",
        "files": entries,
        "total_bytes": sum(item["bytes"] for item in entries),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path, sha256_file(manifest_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the locally verifiable Q-Tail Gate 3 campaign.")
    parser.add_argument("--gate2-report", type=Path, default=DEFAULT_GATE2_REPORT)
    parser.add_argument("--episodes-per-task-per-condition", type=int, default=100)
    parser.add_argument("--max-steps", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20260715)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--require-simulation-pass", action="store_true")
    args = parser.parse_args()
    if args.episodes_per_task_per_condition < 100:
        raise SystemExit("Gate 3 simulation acceptance requires at least 100 episodes per task per condition")

    gate2_path = args.gate2_report.resolve()
    gate2_report = json.loads(gate2_path.read_text(encoding="utf-8"))
    if gate2_report.get("status") != "passed_simulation_controlled":
        raise SystemExit("Gate 2 controlled simulation must pass before Gate 3")
    out = args.out.resolve()
    if out.exists():
        if not args.overwrite:
            raise SystemExit(f"Output exists: {out}; pass --overwrite to replace it")
        shutil.rmtree(out)
    out.mkdir(parents=True)

    episode_rows, task_rows = run_simulation_campaign(
        episodes=args.episodes_per_task_per_condition,
        max_steps=args.max_steps,
        base_seed=args.seed,
    )
    write_csv(out / "simulation_episodes.csv", episode_rows)
    write_csv(out / "simulation_task_summary.csv", task_rows)

    episodes_per_condition = len(episode_rows) // len(CONDITIONS)
    total_violations = sum(
        row["post_clip_bounds_violations"]
        + row["nonfinite_observation_steps"]
        + row["nonfinite_action_steps"]
        + row["nonfinite_reward_steps"]
        + int(bool(row["exception"]))
        for row in episode_rows
    )
    safety = {
        "tail_task_count": len(TASKS),
        "tasks": list(TASKS),
        "conditions": list(CONDITIONS),
        "episodes_per_task_per_condition": args.episodes_per_task_per_condition,
        "episodes_per_condition": episodes_per_condition,
        "total_completed_episodes": len(episode_rows),
        "post_saturation_action_bounds_violations": sum(row["post_clip_bounds_violations"] for row in episode_rows),
        "nonfinite_or_exception_violations": total_violations,
        "raw_action_saturation_events": sum(row["raw_saturation_steps"] for row in episode_rows),
        "simulation_safety_harness_passed": total_violations == 0,
        "interpretation": "Raw policy commands are saturated to the MetaWorld action contract before execution; raw saturation events are disclosed and are not counted as post-contract violations.",
    }
    cost = build_cost_model(gate2_report)
    (out / "safety_metrics.json").write_text(json.dumps(safety, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "cost_model.json").write_text(json.dumps(cost, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(out / "cost_model.csv", [{key: value for key, value in cost.items() if not isinstance(value, (dict, list))}])

    protocol = {
        "generated_at": now(),
        "benchmark": "MetaWorld 3.0.0 MT1",
        "metaworld_version": getattr(metaworld, "__version__", "3.0.0"),
        "mujoco_version": mujoco.__version__,
        "python_version": platform.python_version(),
        "tasks": list(TASKS),
        "conditions": CONDITIONS,
        "episodes_per_task_per_condition": args.episodes_per_task_per_condition,
        "max_steps": args.max_steps,
        "seed": args.seed,
        "gate2_report": str(gate2_path),
        "gate2_report_sha256": sha256_file(gate2_path),
        "claim_boundary": "Local simulation, safety-harness, and modeled-economics evidence only; no customer task, real robot, cross-day site, invoice, or signed procurement acceptance is claimed.",
    }
    (out / "experiment_protocol.json").write_text(json.dumps(protocol, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    (out / "safety_review.md").write_text(
        "# Gate 3 local simulation safety review\n\n"
        f"- Simulator: MetaWorld MT1 / MuJoCo {mujoco.__version__}\n"
        f"- Surrogate tail tasks: {', '.join(TASKS)}\n"
        f"- Completed episodes: {len(episode_rows)} ({episodes_per_condition} per condition)\n"
        f"- Post-contract action bound violations: {safety['post_saturation_action_bounds_violations']}\n"
        f"- Non-finite values or simulator exceptions: {safety['nonfinite_or_exception_violations']}\n"
        f"- Raw commands requiring saturation: {safety['raw_action_saturation_events']}\n\n"
        "This review validates only the software action contract and simulator execution path. "
        "Robot-specific velocity, force, collision, workspace, emergency-stop, and human-presence controls require the buyer's hardware and safety owner.\n",
        encoding="utf-8",
    )
    external = {
        "customer_tail_tasks": {"required": "3-5", "observed": 0, "passed": False},
        "real_robot_trials_per_task": {"required": ">=30", "observed": 0, "passed": False},
        "cross_day_site_reproduction": {"required": True, "observed": False, "passed": False},
        "buyer_acceptance_owner": {"required": True, "observed": False, "passed": False},
        "hardware_safety_review": {"required": True, "observed": False, "passed": False},
        "production_invoice_cost_validation": {"required": True, "observed": False, "passed": False},
        "signed_procurement_contract": {"required": True, "observed": False, "passed": False},
    }
    (out / "external_acceptance_checklist.json").write_text(json.dumps(external, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "external_acceptance_checklist.md").write_text(
        "# Gate 3 external acceptance checklist\n\n"
        "These items cannot be produced by local Docker, downloaded public data, or simulation.\n\n"
        "- [ ] Buyer names 3–5 production tail tasks and an acceptance owner.\n"
        "- [ ] Buyer/operator runs at least 30 real-robot trials per task across days/site conditions.\n"
        "- [ ] Hardware owner signs velocity, force, collision, workspace, E-stop, and human-presence review.\n"
        "- [ ] Finance validates labor, hardware, cloud, failure, and rework invoices.\n"
        "- [ ] Procurement/legal signs the milestone acceptance and production contract.\n",
        encoding="utf-8",
    )

    local_thresholds = {
        "tail_task_count_3_to_5": 3 <= len(TASKS) <= 5,
        "simulation_episodes_per_condition_gte_100": episodes_per_condition >= 100,
        "simulation_safety_harness_passed": safety["simulation_safety_harness_passed"],
        "modeled_unit_cost_reduction_gte_20_pct": cost["threshold_passed"],
    }
    manifest_path, manifest_sha = build_manifest(out)
    report = {
        "gate": 3,
        "status": "local_simulation_ready_external_acceptance_required" if all(local_thresholds.values()) else "local_thresholds_not_met",
        "generated_at": now(),
        "local_thresholds": local_thresholds,
        "safety": safety,
        "cost_model": cost,
        "external_acceptance": external,
        "artifact_manifest": str(manifest_path),
        "artifact_manifest_sha256": manifest_sha,
        "buyer_gate_passed": False,
        "buyer_gate_blocker": "Requires buyer-owned real robot, site, safety, invoice, and signed procurement evidence.",
    }
    (out / "gate3_acceptance_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.require_simulation_pass and not all(local_thresholds.values()):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
