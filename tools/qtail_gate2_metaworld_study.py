#!/usr/bin/env python3
"""Run a same-policy, same-budget MetaWorld closed-loop Q-Tail study.

Two identical multi-task behavior-cloning policies are trained with the same
trajectory budget and optimization schedule. Only the task allocation differs:
an observed-frequency baseline is compared with Q-Tail long-tail allocation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import gymnasium as gym
import numpy as np
import torch
import torch.nn as nn
from lerobot.datasets import LeRobotDataset
from metaworld.policies import ENV_POLICY_MAP


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT.parent / "results" / "qtail_gate2_metaworld_controlled"
TASKS = ("reach-v3", "button-press-v3", "pick-place-v3")
TASK_LABELS = {
    "reach-v3": "head",
    "button-press-v3": "tail",
    "pick-place-v3": "tail",
}


@dataclass
class Trajectory:
    task: str
    episode_seed: int
    observations: np.ndarray
    actions: np.ndarray
    success: bool
    episode_return: float


class PolicyMLP(nn.Module):
    def __init__(self, input_dim: int, hidden_dim: int = 256):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, 4),
            nn.Tanh(),
        )

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        return self.net(features)


def now() -> str:
    return datetime.now(UTC).isoformat()


def parse_allocation(value: str) -> dict[str, int]:
    parts = [int(item) for item in value.split(",")]
    if len(parts) != len(TASKS) or any(item < 1 for item in parts):
        raise argparse.ArgumentTypeError(f"Expected {len(TASKS)} positive comma-separated counts")
    return dict(zip(TASKS, parts, strict=True))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_env(task: str, seed: int):
    return gym.make(
        "Meta-World/MT1",
        env_name=task,
        seed=seed,
        disable_env_checker=True,
    )


def collect_expert_pool(
    allocation_max: dict[str, int],
    *,
    collection_seed: int,
    max_steps: int,
    action_noise: float,
) -> dict[str, list[Trajectory]]:
    pools: dict[str, list[Trajectory]] = {}
    for task_index, task in enumerate(TASKS):
        required = allocation_max[task]
        env = create_env(task, collection_seed + task_index * 100_000)
        expert = ENV_POLICY_MAP[task]()
        trajectories: list[Trajectory] = []
        attempt = 0
        while len(trajectories) < required and attempt < required * 10:
            episode_seed = collection_seed + task_index * 100_000 + attempt
            rng = np.random.default_rng(episode_seed)
            observation, _ = env.reset(seed=episode_seed)
            observations: list[np.ndarray] = []
            actions: list[np.ndarray] = []
            episode_return = 0.0
            success = False
            for _step in range(max_steps):
                expert_action = np.asarray(expert.get_action(observation), dtype=np.float32)
                action = np.clip(expert_action + rng.normal(0.0, action_noise, size=4), -1.0, 1.0).astype(np.float32)
                observations.append(np.asarray(observation, dtype=np.float32))
                actions.append(action)
                observation, reward, terminated, truncated, info = env.step(action)
                episode_return += float(reward)
                success = success or bool(info.get("success"))
                if success or terminated or truncated:
                    break
            if success:
                trajectories.append(Trajectory(
                    task=task,
                    episode_seed=episode_seed,
                    observations=np.stack(observations),
                    actions=np.stack(actions),
                    success=True,
                    episode_return=episode_return,
                ))
            attempt += 1
        env.close()
        if len(trajectories) != required:
            raise RuntimeError(f"Collected only {len(trajectories)}/{required} successful expert trajectories for {task}")
        pools[task] = trajectories
    return pools


def assemble_frames(pools: dict[str, list[Trajectory]], allocation: dict[str, int]) -> tuple[np.ndarray, np.ndarray, dict]:
    features = []
    actions = []
    episode_lengths: dict[str, list[int]] = {}
    for task_index, task in enumerate(TASKS):
        one_hot = np.zeros(len(TASKS), dtype=np.float32)
        one_hot[task_index] = 1.0
        episode_lengths[task] = []
        for trajectory in pools[task][: allocation[task]]:
            task_features = np.repeat(one_hot[None, :], len(trajectory.observations), axis=0)
            features.append(np.concatenate([trajectory.observations, task_features], axis=1))
            actions.append(trajectory.actions)
            episode_lengths[task].append(len(trajectory.observations))
    x = np.concatenate(features).astype(np.float32)
    y = np.concatenate(actions).astype(np.float32)
    summary = {
        "trajectory_allocation": allocation,
        "trajectory_budget": sum(allocation.values()),
        "frames": int(len(x)),
        "episode_lengths": episode_lengths,
    }
    return x, y, summary


def array_sha256(value: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest()


def load_qtail_lerobot_frames(root: Path, allocation: dict[str, int]) -> tuple[np.ndarray, np.ndarray, dict]:
    """Load state/action tensors without decoding video and verify episode allocation."""
    root = root.resolve()
    manifest_path = root / "package_manifest.json"
    index_path = root / "trajectory_index.json"
    if not manifest_path.is_file() or not index_path.is_file():
        raise RuntimeError(f"Gate 1 package metadata is incomplete: {root}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("product") != "qtail_gate1_metaworld_synthetic_trajectory_package":
        raise RuntimeError("Gate 2 received an unsupported Gate 1 package")
    if manifest.get("trajectory_allocation") != allocation:
        raise RuntimeError("Gate 1 package allocation does not match the Gate 2 Q-Tail allocation")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    observed_allocation = {task: sum(1 for row in index if row.get("task") == task) for task in TASKS}
    if observed_allocation != allocation:
        raise RuntimeError("Gate 1 trajectory index allocation does not match its manifest")

    dataset = LeRobotDataset("qtail/metaworld-sawyer-gate1-v3", root=root, return_uint8=True)
    columns = dataset.hf_dataset.to_dict()
    states = np.asarray(columns["observation.state"], dtype=np.float32)
    actions = np.asarray(columns["action"], dtype=np.float32)
    task_indices = np.asarray(columns["task_index"], dtype=np.int64)
    episode_indices = np.asarray(columns["episode_index"], dtype=np.int64)
    if states.ndim != 2 or states.shape[1] != 39 or actions.shape != (len(states), 4):
        raise RuntimeError("Gate 1 LeRobot tensors do not match the Sawyer state/action contract")
    if not np.isfinite(states).all() or not np.isfinite(actions).all():
        raise RuntimeError("Gate 1 LeRobot tensors contain non-finite values")
    if set(np.unique(task_indices).tolist()) != set(range(len(TASKS))):
        raise RuntimeError("Gate 1 LeRobot task indices are incomplete")
    one_hot = np.eye(len(TASKS), dtype=np.float32)[task_indices]
    features = np.concatenate([states, one_hot], axis=1).astype(np.float32)
    episode_lengths = {
        task: [int(row["steps"]) for row in index if row.get("task") == task]
        for task in TASKS
    }
    summary = {
        "trajectory_allocation": allocation,
        "trajectory_budget": sum(allocation.values()),
        "frames": int(len(features)),
        "episode_lengths": episode_lengths,
        "training_source": "Gate 1 validated LeRobotDataset v3 synthetic simulator package",
        "training_source_root": str(root),
        "training_source_manifest_sha256": sha256_file(manifest_path),
        "training_source_episode_count": int(len(np.unique(episode_indices))),
        "training_feature_sha256": array_sha256(features),
        "training_action_sha256": array_sha256(actions),
    }
    if summary["training_source_episode_count"] != sum(allocation.values()):
        raise RuntimeError("Gate 1 LeRobot episode count does not match the expected budget")
    return features, actions, summary


def train_policy(
    x: np.ndarray,
    y: np.ndarray,
    *,
    seed: int,
    steps: int,
    batch_size: int,
    learning_rate: float,
) -> tuple[PolicyMLP, np.ndarray, np.ndarray, list[dict]]:
    torch.manual_seed(seed)
    np_rng = np.random.default_rng(seed)
    mean = x.mean(axis=0).astype(np.float32)
    std = x.std(axis=0).astype(np.float32)
    std[std < 1e-6] = 1.0
    normalized = (x - mean) / std
    x_tensor = torch.from_numpy(normalized)
    y_tensor = torch.from_numpy(y)
    model = PolicyMLP(x.shape[1])
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=1e-5)
    loss_fn = nn.MSELoss()
    log: list[dict] = []
    for step in range(1, steps + 1):
        indices = np_rng.integers(0, len(x), size=batch_size)
        prediction = model(x_tensor[indices])
        loss = loss_fn(prediction, y_tensor[indices])
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()
        if step == 1 or step % 100 == 0 or step == steps:
            log.append({"step": step, "loss": float(loss.detach())})
    return model, mean, std, log


def policy_action(model: PolicyMLP, mean: np.ndarray, std: np.ndarray, observation: np.ndarray, task_index: int) -> np.ndarray:
    one_hot = np.zeros(len(TASKS), dtype=np.float32)
    one_hot[task_index] = 1.0
    features = np.concatenate([np.asarray(observation, dtype=np.float32), one_hot])
    normalized = (features - mean) / std
    with torch.no_grad():
        action = model(torch.from_numpy(normalized).unsqueeze(0)).squeeze(0).cpu().numpy()
    return np.clip(action, -1.0, 1.0).astype(np.float32)


def evaluate_policy(
    condition: str,
    model: PolicyMLP,
    mean: np.ndarray,
    std: np.ndarray,
    *,
    model_seed: int,
    eval_episodes: int,
    eval_seed: int,
    max_steps: int,
) -> list[dict]:
    rows: list[dict] = []
    model.eval()
    for task_index, task in enumerate(TASKS):
        env = create_env(task, eval_seed + task_index * 100_000)
        for episode_index in range(eval_episodes):
            episode_seed = eval_seed + model_seed * 1_000_000 + task_index * 100_000 + episode_index
            observation, _ = env.reset(seed=episode_seed)
            episode_return = 0.0
            success = False
            length = 0
            for step in range(max_steps):
                action = policy_action(model, mean, std, observation, task_index)
                observation, reward, terminated, truncated, info = env.step(action)
                episode_return += float(reward)
                success = success or bool(info.get("success"))
                length = step + 1
                if success or terminated or truncated:
                    break
            rows.append({
                "condition": condition,
                "model_seed": model_seed,
                "task": task,
                "task_group": TASK_LABELS[task],
                "episode_index": episode_index,
                "episode_seed": episode_seed,
                "success": int(success),
                "return": episode_return,
                "length": length,
            })
        env.close()
    return rows


def success_rate(rows: list[dict], condition: str, tasks: set[str]) -> float:
    values = [row["success"] for row in rows if row["condition"] == condition and row["task"] in tasks]
    return float(np.mean(values)) if values else 0.0


def paired_tail_ci(rows: list[dict], *, bootstrap_samples: int = 10_000) -> tuple[float, float]:
    tail_tasks = {task for task in TASKS if TASK_LABELS[task] == "tail"}
    paired: dict[tuple, dict[str, int]] = {}
    for row in rows:
        if row["task"] not in tail_tasks:
            continue
        key = (row["model_seed"], row["task"], row["episode_index"], row["episode_seed"])
        paired.setdefault(key, {})[row["condition"]] = row["success"]
    differences = np.array([
        item["qtail"] - item["baseline"]
        for item in paired.values()
        if "baseline" in item and "qtail" in item
    ], dtype=np.float64)
    if not len(differences):
        raise RuntimeError("No paired tail evaluation rows")
    rng = np.random.default_rng(20260715)
    means = np.empty(bootstrap_samples, dtype=np.float64)
    for index in range(bootstrap_samples):
        means[index] = rng.choice(differences, size=len(differences), replace=True).mean()
    return float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def save_checkpoint(path: Path, model: PolicyMLP, mean: np.ndarray, std: np.ndarray, metadata: dict) -> None:
    torch.save({
        "state_dict": model.state_dict(),
        "observation_mean": torch.from_numpy(mean),
        "observation_std": torch.from_numpy(std),
        "metadata": metadata,
    }, path)


def build_manifest(out: Path) -> tuple[Path, str]:
    artifact_files = sorted(path for path in out.rglob("*") if path.is_file() and path.name not in {"artifact_manifest.json", "gate2_acceptance_report.json"})
    entries = [
        {"path": str(path.relative_to(out)), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
        for path in artifact_files
    ]
    manifest_path = out / "artifact_manifest.json"
    manifest_path.write_text(json.dumps({
        "generated_at": now(),
        "experiment": "qtail_gate2_same_policy_same_budget_metaworld",
        "files": entries,
        "total_bytes": sum(item["bytes"] for item in entries),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path, sha256_file(manifest_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Q-Tail controlled MetaWorld Gate 2 study.")
    parser.add_argument("--baseline-allocation", type=parse_allocation, default=parse_allocation("60,3,1"))
    parser.add_argument("--qtail-allocation", type=parse_allocation, default=parse_allocation("50,7,7"))
    parser.add_argument("--model-seeds", default="17,29,43")
    parser.add_argument("--collection-seed", type=int, default=20260715)
    parser.add_argument("--eval-seed", type=int, default=20260801)
    parser.add_argument("--train-steps", type=int, default=5000)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--eval-episodes", type=int, default=50)
    parser.add_argument("--max-steps", type=int, default=200)
    parser.add_argument("--expert-action-noise", type=float, default=0.02)
    parser.add_argument(
        "--qtail-lerobot-root",
        type=Path,
        help="Validated Gate 1 synthetic LeRobot package to use as the Q-Tail training condition.",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args()

    if sum(args.baseline_allocation.values()) != sum(args.qtail_allocation.values()):
        raise SystemExit("Baseline and Q-Tail trajectory budgets must be identical")
    model_seeds = [int(value) for value in args.model_seeds.split(",") if value.strip()]
    if not model_seeds:
        raise SystemExit("At least one model seed is required")
    out = args.out.resolve()
    if out.exists():
        if not args.overwrite:
            raise SystemExit(f"Output exists: {out}; pass --overwrite to replace it")
        shutil.rmtree(out)
    out.mkdir(parents=True)

    allocation_max = {
        task: max(args.baseline_allocation[task], args.qtail_allocation[task])
        for task in TASKS
    }
    pools = collect_expert_pool(
        allocation_max,
        collection_seed=args.collection_seed,
        max_steps=args.max_steps,
        action_noise=args.expert_action_noise,
    )
    baseline_x, baseline_y, baseline_data = assemble_frames(pools, args.baseline_allocation)
    collected_qtail_x, collected_qtail_y, collected_qtail_data = assemble_frames(pools, args.qtail_allocation)
    if args.qtail_lerobot_root:
        qtail_x, qtail_y, qtail_data = load_qtail_lerobot_frames(args.qtail_lerobot_root, args.qtail_allocation)
        if qtail_x.shape != collected_qtail_x.shape or qtail_y.shape != collected_qtail_y.shape:
            raise RuntimeError("Gate 1 package tensor shapes do not match deterministic simulator recollection")
        if not np.allclose(qtail_x, collected_qtail_x, rtol=0.0, atol=1e-6):
            raise RuntimeError("Gate 1 package observations do not match deterministic simulator recollection")
        if not np.allclose(qtail_y, collected_qtail_y, rtol=0.0, atol=1e-6):
            raise RuntimeError("Gate 1 package actions do not match deterministic simulator recollection")
        qtail_data["deterministic_recollection_match"] = True
        qtail_data["recollection_feature_sha256"] = array_sha256(collected_qtail_x)
        qtail_data["recollection_action_sha256"] = array_sha256(collected_qtail_y)
    else:
        qtail_x, qtail_y, qtail_data = collected_qtail_x, collected_qtail_y, collected_qtail_data

    protocol = {
        "generated_at": now(),
        "benchmark": "MetaWorld 3.0.0 MT1",
        "tasks": [{"name": task, "group": TASK_LABELS[task]} for task in TASKS],
        "same_policy": True,
        "same_budget": True,
        "policy": "39-state + 3-task-one-hot -> MLP(256,256,256) -> 4D tanh action",
        "optimizer": "AdamW",
        "train_steps": args.train_steps,
        "batch_size": args.batch_size,
        "learning_rate": args.learning_rate,
        "max_episode_steps": args.max_steps,
        "evaluation_episodes_per_task_per_seed": args.eval_episodes,
        "model_seeds": model_seeds,
        "baseline": baseline_data,
        "qtail": qtail_data,
        "claim_boundary": "Simulation closed-loop evidence only; no real-robot or buyer production claim.",
    }
    (out / "experiment_protocol.json").write_text(json.dumps(protocol, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    evaluation_rows: list[dict] = []
    training_rows: list[dict] = []
    for model_seed in model_seeds:
        trained: dict[str, tuple[PolicyMLP, np.ndarray, np.ndarray]] = {}
        for condition, x, y, data_summary in (
            ("baseline", baseline_x, baseline_y, baseline_data),
            ("qtail", qtail_x, qtail_y, qtail_data),
        ):
            model, mean, std, log = train_policy(
                x,
                y,
                seed=model_seed,
                steps=args.train_steps,
                batch_size=args.batch_size,
                learning_rate=args.learning_rate,
            )
            trained[condition] = (model, mean, std)
            training_rows.extend({"condition": condition, "model_seed": model_seed, **item} for item in log)
            save_checkpoint(
                out / f"{condition}_policy_seed_{model_seed}.pt",
                model,
                mean,
                std,
                {"condition": condition, "model_seed": model_seed, **data_summary},
            )
        for condition in ("baseline", "qtail"):
            model, mean, std = trained[condition]
            evaluation_rows.extend(evaluate_policy(
                condition,
                model,
                mean,
                std,
                model_seed=model_seed,
                eval_episodes=args.eval_episodes,
                eval_seed=args.eval_seed,
                max_steps=args.max_steps,
            ))

    write_csv(out / "training_log.csv", training_rows)
    write_csv(out / "evaluation_episodes.csv", evaluation_rows)
    head_tasks = {task for task in TASKS if TASK_LABELS[task] == "head"}
    tail_tasks = {task for task in TASKS if TASK_LABELS[task] == "tail"}
    all_tasks = set(TASKS)
    rates = {
        condition: {
            "head_success_rate": success_rate(evaluation_rows, condition, head_tasks),
            "tail_success_rate": success_rate(evaluation_rows, condition, tail_tasks),
            "overall_success_rate": success_rate(evaluation_rows, condition, all_tasks),
            "per_task": {
                task: success_rate(evaluation_rows, condition, {task})
                for task in TASKS
            },
        }
        for condition in ("baseline", "qtail")
    }
    ci_lower, ci_upper = paired_tail_ci(evaluation_rows)
    tail_gain_pp = (rates["qtail"]["tail_success_rate"] - rates["baseline"]["tail_success_rate"]) * 100
    overall_gain_pp = (rates["qtail"]["overall_success_rate"] - rates["baseline"]["overall_success_rate"]) * 100
    head_gain_pp = (rates["qtail"]["head_success_rate"] - rates["baseline"]["head_success_rate"]) * 100
    metrics = {
        "baseline_name": "observed-frequency allocation " + "/".join(str(args.baseline_allocation[task]) for task in TASKS),
        "qtail_name": "Q-Tail allocation " + "/".join(str(args.qtail_allocation[task]) for task in TASKS),
        "same_policy": True,
        "same_budget": True,
        "trajectory_budget_per_condition": sum(args.baseline_allocation.values()),
        "evaluation_episodes_per_condition": len(evaluation_rows) // 2,
        "rates": rates,
        "tail_sr_gain_pp": tail_gain_pp,
        "ci95_lower_pp": ci_lower * 100,
        "ci95_upper_pp": ci_upper * 100,
        "overall_gain_pp": overall_gain_pp,
        "head_gain_pp": head_gain_pp,
    }
    thresholds = {
        "tail_sr_gain_pp_gte_5": tail_gain_pp >= 5.0,
        "ci95_lower_pp_gt_0": ci_lower > 0.0,
        "overall_gain_pp_gte_minus_1": overall_gain_pp >= -1.0,
        "head_gain_pp_gte_minus_2": head_gain_pp >= -2.0,
    }
    (out / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest_path, manifest_sha256 = build_manifest(out)
    report = {
        "gate": 2,
        "status": "passed_simulation_controlled" if all(thresholds.values()) else "thresholds_not_met",
        "generated_at": now(),
        "metrics": metrics,
        "thresholds": thresholds,
        "artifact_manifest": str(manifest_path),
        "artifact_manifest_sha256": manifest_sha256,
        "evidence_level": "controlled MetaWorld closed-loop simulation",
        "buyer_gate_status": "requires independent buyer reproduction/operator review before production approval",
    }
    (out / "gate2_acceptance_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.require_pass and not all(thresholds.values()):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
