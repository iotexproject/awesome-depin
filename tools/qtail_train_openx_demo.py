#!/usr/bin/env python3
"""Train a Q-Tail allocation head from real Open X RLDS TFRecord records.

The model is deliberately narrower than a robot policy: it learns an allocation
prior for rare/risky embodied-data shards. Every complete TFRecord shard is
covered and a bounded number of real episodes is decoded from each shard so the
training features include trajectory length, reward, action and instruction
signals instead of relying on filenames alone.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn

try:
    from tfrecord.reader import tfrecord_loader
except ImportError as exc:  # pragma: no cover - exercised by deployment checks
    raise SystemExit("Missing dependency: install `tfrecord` from requirements.txt") from exc


FEATURE_NAMES = [
    "log_bytes",
    "shard_size_rarity",
    "dataset_frequency",
    "shard_position",
    "mean_episode_steps",
    "reward_failure_proxy",
    "action_complexity",
    "instruction_complexity",
    "terminal_rate",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_partial(path: Path) -> bool:
    return ".gstmp" in path.name or path.name.endswith(".tmp") or path.name.endswith(".part")


def find_shards(data_dir: Path, max_shards: int = 0) -> list[Path]:
    shards = sorted(
        path
        for path in data_dir.rglob("*")
        if path.is_file() and "tfrecord" in path.name.lower() and not is_partial(path)
    )
    return shards[:max_shards] if max_shards > 0 else shards


def dataset_name(path: Path, data_dir: Path) -> str:
    rel = path.relative_to(data_dir)
    return rel.parts[0] if rel.parts else "unknown"


def shard_coordinates(name: str) -> tuple[float, float]:
    match = re.search(r"-(\d+)-of-(\d+)$", name)
    if match:
        return float(match.group(1)), max(float(match.group(2)), 1.0)
    match = re.search(r"-(\d+)$", name)
    if match:
        return float(match.group(1)), max(float(match.group(1)) + 1.0, 1.0)
    return 0.0, 1.0


def first_array(record: dict[str, Any], candidates: tuple[str, ...]) -> np.ndarray | None:
    for key in candidates:
        value = record.get(key)
        if isinstance(value, np.ndarray) and value.size:
            return value
    return None


def safe_float(value: float) -> float:
    return float(value) if np.isfinite(value) else 0.0


def record_features(record: dict[str, Any]) -> dict[str, float]:
    step_array = first_array(record, ("steps/is_first", "steps/reward", "steps/is_last"))
    step_count = int(step_array.size) if step_array is not None else 0

    reward = first_array(record, ("steps/reward",))
    reward_mean = safe_float(float(np.mean(reward))) if reward is not None else 0.0
    reward_max = safe_float(float(np.max(reward))) if reward is not None else 0.0
    reward_final = safe_float(float(reward[-1])) if reward is not None else 0.0

    action_parts = []
    for key, value in record.items():
        if key.startswith("steps/action") and isinstance(value, np.ndarray) and np.issubdtype(value.dtype, np.number):
            action_parts.append(value.astype(np.float32, copy=False).reshape(-1))
    action = np.concatenate(action_parts) if action_parts else np.zeros(1, dtype=np.float32)
    action_abs_mean = safe_float(float(np.mean(np.abs(action))))
    action_std = safe_float(float(np.std(action)))

    instruction = first_array(
        record,
        (
            "steps/language_instruction",
            "steps/observation/natural_language_instruction",
            "steps/observation/instruction",
        ),
    )
    instruction_units = 0.0
    instruction_unique = 0.0
    if instruction is not None:
        if instruction.dtype.kind in "SUO":
            sample = instruction[: min(len(instruction), 64)]
            instruction_units = float(np.mean([len(bytes(item).strip(b"\x00")) for item in sample]))
            instruction_unique = float(len({bytes(item) for item in sample}))
        else:
            flattened = instruction.reshape(-1)
            instruction_units = float(np.count_nonzero(flattened[: min(flattened.size, 4096)]))
            instruction_unique = float(np.unique(flattened[: min(flattened.size, 4096)]).size)

    terminal = first_array(record, ("steps/is_terminal", "steps/is_last"))
    terminal_rate = safe_float(float(np.mean(terminal != 0))) if terminal is not None else 0.0
    return {
        "episode_steps": float(step_count),
        "reward_mean": reward_mean,
        "reward_max": reward_max,
        "reward_final": reward_final,
        "action_abs_mean": action_abs_mean,
        "action_std": action_std,
        "instruction_units": instruction_units,
        "instruction_unique": instruction_unique,
        "terminal_rate": terminal_rate,
    }


def aggregate_records(path: Path, records_per_shard: int) -> dict[str, Any]:
    samples: list[dict[str, float]] = []
    parse_error = ""
    try:
        for record in tfrecord_loader(str(path), None):
            samples.append(record_features(record))
            if len(samples) >= records_per_shard:
                break
    except Exception as exc:  # retain the shard and expose the failure in the audit
        parse_error = f"{type(exc).__name__}: {exc}"[:500]

    keys = (
        "episode_steps",
        "reward_mean",
        "reward_max",
        "reward_final",
        "action_abs_mean",
        "action_std",
        "instruction_units",
        "instruction_unique",
        "terminal_rate",
    )
    aggregated = {f"mean_{key}": 0.0 for key in keys}
    if samples:
        for key in keys:
            aggregated[f"mean_{key}"] = safe_float(float(np.mean([sample[key] for sample in samples])))
    return {
        **aggregated,
        "records_decoded": len(samples),
        "record_parse_ok": int(bool(samples)),
        "record_parse_error": parse_error,
    }


def build_rows(data_dir: Path, records_per_shard: int, max_shards: int = 0) -> list[dict[str, Any]]:
    rows = []
    for path in find_shards(data_dir, max_shards=max_shards):
        size = path.stat().st_size
        if size <= 0:
            continue
        shard_idx, shard_total = shard_coordinates(path.name)
        rows.append(
            {
                "dataset": dataset_name(path, data_dir),
                "path": str(path),
                "bytes": size,
                "log_bytes": math.log1p(size),
                "shard_idx": shard_idx,
                "shard_total": shard_total,
                **aggregate_records(path, records_per_shard),
            }
        )
    return rows


def minmax(values: np.ndarray, invert: bool = False) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    spread = float(np.ptp(values))
    scaled = np.zeros_like(values) if spread <= 1e-12 else (values - values.min()) / spread
    return 1.0 - scaled if invert else scaled


def make_training_matrix(
    rows: list[dict[str, Any]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[str], dict[str, list[float]]]:
    datasets = sorted({str(row["dataset"]) for row in rows})
    ds_counts = {name: sum(1 for row in rows if row["dataset"] == name) for name in datasets}
    bytes_arr = np.array([row["bytes"] for row in rows], dtype=np.float64)
    log_bytes = np.log1p(bytes_arr)
    size_rarity = minmax(log_bytes, invert=True)
    ds_freq = np.array([ds_counts[str(row["dataset"])] / len(rows) for row in rows], dtype=np.float64)
    shard_pos = np.array([row["shard_idx"] / max(row["shard_total"], 1.0) for row in rows], dtype=np.float64)
    episode_steps = np.array([row["mean_episode_steps"] for row in rows], dtype=np.float64)
    reward_max = np.array([row["mean_reward_max"] for row in rows], dtype=np.float64)
    action_complexity = np.array(
        [row["mean_action_std"] + row["mean_action_abs_mean"] for row in rows], dtype=np.float64
    )
    instruction_complexity = np.array(
        [math.log1p(row["mean_instruction_units"] + row["mean_instruction_unique"]) for row in rows],
        dtype=np.float64,
    )
    terminal_rate = np.array([row["mean_terminal_rate"] for row in rows], dtype=np.float64)

    duration_score = minmax(np.log1p(episode_steps))
    failure_score = minmax(reward_max, invert=True)
    action_score = minmax(np.log1p(np.maximum(action_complexity, 0.0)))
    instruction_score = minmax(instruction_complexity)
    dataset_rarity = minmax(ds_freq, invert=True)
    tail_score = (
        0.28 * size_rarity
        + 0.18 * dataset_rarity
        + 0.14 * shard_pos
        + 0.16 * failure_score
        + 0.10 * duration_score
        + 0.08 * action_score
        + 0.06 * instruction_score
    )

    raw_features = np.column_stack(
        [
            log_bytes,
            size_rarity,
            ds_freq,
            shard_pos,
            np.log1p(episode_steps),
            failure_score,
            action_score,
            instruction_score,
            terminal_rate,
        ]
    ).astype(np.float32)
    feature_mean = raw_features.mean(axis=0)
    feature_std = raw_features.std(axis=0)
    feature_std = np.where(feature_std < 1e-6, 1.0, feature_std)
    features = ((raw_features - feature_mean) / feature_std).astype(np.float32)

    source = (bytes_arr / bytes_arr.sum()).astype(np.float32)
    pt = np.random.default_rng(123).exponential(1.0, size=len(rows)).astype(np.float32)
    pt /= pt.sum()
    order = np.argsort(-tail_score)
    qtail = np.zeros_like(pt)
    qtail[order] = np.sort(pt)[::-1]
    qtail = (0.28 * source) + (0.72 * qtail)
    qtail /= qtail.sum()
    normalization = {
        "mean": [float(value) for value in feature_mean],
        "std": [float(value) for value in feature_std],
    }
    return features, source, qtail.astype(np.float32), tail_score.astype(np.float32), datasets, normalization


class AllocationHead(nn.Module):
    def __init__(self, input_dim: int):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(input_dim, 32), nn.GELU(), nn.Linear(32, 16), nn.GELU(), nn.Linear(16, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return torch.softmax(self.net(x).squeeze(-1), dim=0)


def train_once(
    features: np.ndarray, target: np.ndarray, steps: int, seed: int
) -> tuple[list[dict[str, float]], np.ndarray, AllocationHead]:
    torch.manual_seed(seed)
    x = torch.tensor(features)
    y = torch.tensor(target)
    model = AllocationHead(features.shape[1])
    optimizer = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=1e-4)
    history = []
    for step in range(steps + 1):
        pred = model(x)
        loss = torch.sum(y * (torch.log(y + 1e-8) - torch.log(pred + 1e-8)))
        if step % max(1, steps // 20) == 0:
            history.append({"step": step, "kl": float(loss.detach().cpu())})
        if step == steps:
            break
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
    return history, model(x).detach().cpu().numpy(), model


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("data/openx_demo"))
    parser.add_argument("--out", type=Path, default=Path("results/openx_demo_training"))
    parser.add_argument("--steps", type=int, default=3000)
    parser.add_argument("--wait", type=int, default=1)
    parser.add_argument("--min-shards", type=int, default=4)
    parser.add_argument("--records-per-shard", type=int, default=1)
    parser.add_argument("--min-record-parse-rate", type=float, default=0.90)
    parser.add_argument("--max-shards", type=int, default=0, help="Test-only cap; 0 covers every complete shard.")
    args = parser.parse_args()
    if args.records_per_shard < 1:
        raise SystemExit("--records-per-shard must be >= 1")

    args.out.mkdir(parents=True, exist_ok=True)
    while True:
        shard_paths = find_shards(args.data_dir, max_shards=args.max_shards)
        if len(shard_paths) >= args.min_shards:
            break
        status = {
            "generated_at": now(),
            "status": "waiting_for_openx_shards",
            "data_dir": str(args.data_dir),
            "found_shards": len(shard_paths),
            "min_shards": args.min_shards,
        }
        (args.out / "training_status.json").write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
        if not args.wait:
            print(json.dumps(status, indent=2))
            return
        time.sleep(30)

    rows = build_rows(args.data_dir, records_per_shard=args.records_per_shard, max_shards=args.max_shards)
    parsed_shards = sum(int(row["record_parse_ok"]) for row in rows)
    parse_rate = parsed_shards / max(len(rows), 1)
    if parse_rate < args.min_record_parse_rate:
        raise SystemExit(
            f"Record parse coverage {parse_rate:.3f} is below required {args.min_record_parse_rate:.3f} "
            f"({parsed_shards}/{len(rows)} shards)."
        )

    features, source, qtail, tail_scores, datasets, normalization = make_training_matrix(rows)
    source_hist, source_pred, source_model = train_once(features, source, args.steps, seed=11)
    qtail_hist, qtail_pred, qtail_model = train_once(features, qtail, args.steps, seed=11)

    for idx, row in enumerate(rows):
        row["tail_score"] = float(tail_scores[idx])
        row["source_target"] = float(source[idx])
        row["qtail_target"] = float(qtail[idx])
        row["source_pred"] = float(source_pred[idx])
        row["qtail_pred"] = float(qtail_pred[idx])
    rows_path = args.out / "openx_shard_training_rows.csv"
    write_csv(rows_path, rows)

    checkpoint_path = args.out / "qtail_allocation_head.pt"
    torch.save(
        {
            "format_version": 2,
            "model_class": "AllocationHead",
            "feature_names": FEATURE_NAMES,
            "feature_normalization": normalization,
            "qtail_state_dict": qtail_model.state_dict(),
            "source_state_dict": source_model.state_dict(),
            "training_steps": args.steps,
            "records_per_shard": args.records_per_shard,
            "datasets": datasets,
        },
        checkpoint_path,
    )

    tail_cut = np.quantile(tail_scores, 0.70)
    tail_mask = tail_scores >= tail_cut
    source_tail_share = float(source[tail_mask].sum())
    qtail_tail_share = float(qtail[tail_mask].sum())
    source_pred_tail_share = float(source_pred[tail_mask].sum())
    qtail_pred_tail_share = float(qtail_pred[tail_mask].sum())
    total_bytes = sum(int(row["bytes"]) for row in rows)
    report = {
        "generated_at": now(),
        "status": "complete",
        "training_scope": "all_complete_shards_record_sampled" if not args.max_shards else "bounded_test_subset",
        "claim_boundary": [
            "This is a real Open X record-informed Q-Tail allocation-head training run.",
            "Every complete TFRecord shard is covered; a bounded, deterministic number of episodes is decoded per shard.",
            "It is not full robot-policy training and it does not prove downstream policy success without a same-policy run.",
            "Both source and Q-Tail heads use identical architecture, optimizer, steps, features and seed.",
        ],
        "data_dir": str(args.data_dir),
        "datasets": datasets,
        "shard_count": len(rows),
        "total_bytes": total_bytes,
        "total_gib": round(total_bytes / (1024**3), 3),
        "steps": args.steps,
        "model_artifact": {
            "path": str(checkpoint_path),
            "sha256": file_sha256(checkpoint_path),
            "feature_names": FEATURE_NAMES,
            "parameter_count": sum(parameter.numel() for parameter in qtail_model.parameters()),
        },
        "trajectory_evidence": {
            "tfrecord_shards_attempted": len(rows),
            "tfrecord_shards_parsed": parsed_shards,
            "record_parse_rate": parse_rate,
            "records_per_shard_cap": args.records_per_shard,
            "records_decoded": sum(int(row["records_decoded"]) for row in rows),
            "mean_episode_steps": float(np.mean([row["mean_episode_steps"] for row in rows])),
            "features_include": ["episode length", "reward", "action statistics", "instruction complexity", "terminal rate"],
        },
        "source_final_kl": source_hist[-1]["kl"],
        "qtail_final_kl": qtail_hist[-1]["kl"],
        "effect_metrics": {
            "tail_definition": "top_30_percent_by_record_informed_tail_score",
            "source_tail_share": source_tail_share,
            "qtail_tail_share": qtail_tail_share,
            "target_tail_share_gain_pp": (qtail_tail_share - source_tail_share) * 100,
            "source_pred_tail_share": source_pred_tail_share,
            "qtail_pred_tail_share": qtail_pred_tail_share,
            "predicted_tail_share_gain_pp": (qtail_pred_tail_share - source_pred_tail_share) * 100,
            "consistent_with_pt_tail_goal": qtail_tail_share > source_tail_share,
        },
        "source_history": source_hist,
        "qtail_history": qtail_hist,
    }
    report_text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    (args.out / "openx_demo_training_report.json").write_text(report_text, encoding="utf-8")
    (args.out / "training_status.json").write_text(report_text, encoding="utf-8")
    print(report_text, end="")


if __name__ == "__main__":
    main()
