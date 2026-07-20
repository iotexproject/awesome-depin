#!/usr/bin/env python3
"""Export Q-Tail-selected Open X episodes as a validated LeRobot v3 dataset.

This is a production-adapter baseline for Gate 1. It converts real RLDS
episodes into trainable LeRobot v3 Parquet/MP4 shards and validates the result
with the official LeRobot loader. It does not claim that the source episodes
are newly synthesized or buyer-specific trajectories.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import shutil
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from tfrecord.reader import tfrecord_loader
from torch.utils.data import DataLoader

from lerobot.datasets import LeRobotDataset, LeRobotDatasetMetadata


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT.parent / "data" / "openx_demo" / "ucsd_kitchen_dataset_converted_externally_to_rlds" / "0.1.0"
DEFAULT_OUT = ROOT.parent / "results" / "qtail_gate1_trajectory_delivery"
REPO_ID = "qtail/ucsd-kitchen-gate1-v3"
DATASET_NAME = "ucsd_kitchen_dataset_converted_externally_to_rlds"


@dataclass(frozen=True)
class EpisodeProfile:
    source_id: str
    shard: str
    record_index: int
    instruction: str
    steps: int
    action_abs_mean: float
    action_std: float
    reward_max: float
    reward_final: float
    instruction_frequency: int = 0
    qtail_score: float = 0.0


def now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def complete_shards(source: Path) -> list[Path]:
    return sorted(
        path
        for path in source.iterdir()
        if path.is_file()
        and "tfrecord" in path.name.lower()
        and not any(marker in path.name for marker in (".gstmp", ".tmp", ".part"))
    )


def decode_instruction(record: dict, steps: int) -> str:
    values = record.get("steps/language_instruction")
    if isinstance(values, np.ndarray) and values.size:
        raw = bytes(values.reshape(-1)[0]).rstrip(b"\x00")
        text = raw.decode("utf-8", errors="replace").strip()
        if text:
            return text
    return "UCSD kitchen manipulation"


def profile_record(record: dict, shard: Path, record_index: int) -> EpisodeProfile:
    steps = int(np.asarray(record["steps/is_first"]).size)
    action = np.asarray(record["steps/action"], dtype=np.float32).reshape(steps, 8)
    reward = np.asarray(record["steps/reward"], dtype=np.float32).reshape(steps)
    instruction = decode_instruction(record, steps)
    source_id = f"{shard.name}:{record_index}"
    return EpisodeProfile(
        source_id=source_id,
        shard=shard.name,
        record_index=record_index,
        instruction=instruction,
        steps=steps,
        action_abs_mean=float(np.mean(np.abs(action))),
        action_std=float(np.std(action)),
        reward_max=float(np.max(reward)) if reward.size else 0.0,
        reward_final=float(reward[-1]) if reward.size else 0.0,
    )


def scan_profiles(shards: list[Path]) -> list[EpisodeProfile]:
    profiles: list[EpisodeProfile] = []
    for shard in shards:
        for record_index, record in enumerate(tfrecord_loader(str(shard), None)):
            profiles.append(profile_record(record, shard, record_index))
    if not profiles:
        raise RuntimeError("No RLDS episodes could be decoded")
    return profiles


def minmax(values: np.ndarray, *, invert: bool = False) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    spread = float(np.ptp(values))
    scaled = np.zeros_like(values) if spread <= 1e-12 else (values - values.min()) / spread
    return 1.0 - scaled if invert else scaled


def porter_thomas_score(source_id: str) -> float:
    raw = hashlib.sha256(source_id.encode("utf-8")).digest()[:8]
    uniform = (int.from_bytes(raw, "big") + 1) / (2**64 + 1)
    return -math.log(max(uniform, 1e-12))


def score_profiles(profiles: list[EpisodeProfile]) -> list[EpisodeProfile]:
    frequencies = Counter(profile.instruction for profile in profiles)
    lengths = minmax(np.array([profile.steps for profile in profiles], dtype=np.float64))
    action = minmax(np.array([profile.action_std + profile.action_abs_mean for profile in profiles], dtype=np.float64))
    failures = minmax(np.array([profile.reward_max for profile in profiles], dtype=np.float64), invert=True)
    rarity = minmax(np.array([frequencies[profile.instruction] for profile in profiles], dtype=np.float64), invert=True)
    pt = minmax(np.array([porter_thomas_score(profile.source_id) for profile in profiles], dtype=np.float64))
    result = []
    for index, profile in enumerate(profiles):
        score = 0.22 * lengths[index] + 0.18 * action[index] + 0.18 * failures[index] + 0.18 * rarity[index] + 0.24 * pt[index]
        result.append(EpisodeProfile(
            **{
                **asdict(profile),
                "instruction_frequency": frequencies[profile.instruction],
                "qtail_score": float(score),
            }
        ))
    return sorted(result, key=lambda item: (-item.qtail_score, item.source_id))


def feature_contract() -> dict:
    return {
        "observation.state": {
            "dtype": "float32",
            "shape": (21,),
            "names": [f"state_{index}" for index in range(21)],
        },
        "observation.images.rgb": {
            "dtype": "video",
            "shape": (480, 640, 3),
            "names": ["height", "width", "channels"],
        },
        "action": {
            "dtype": "float32",
            "shape": (8,),
            "names": [f"action_{index}" for index in range(8)],
        },
        "reward": {"dtype": "float32", "shape": (1,), "names": ["reward"]},
        "discount": {"dtype": "float32", "shape": (1,), "names": ["discount"]},
        "done": {"dtype": "bool", "shape": (1,), "names": ["done"]},
    }


def reshape_record(record: dict) -> dict:
    steps = int(np.asarray(record["steps/is_first"]).size)
    arrays = {
        "action": np.asarray(record["steps/action"], dtype=np.float32).reshape(steps, 8),
        "state": np.asarray(record["steps/observation/state"], dtype=np.float32).reshape(steps, 21),
        "reward": np.asarray(record["steps/reward"], dtype=np.float32).reshape(steps),
        "discount": np.asarray(record["steps/discount"], dtype=np.float32).reshape(steps),
        "done": np.asarray(record["steps/is_last"], dtype=np.int64).astype(bool).reshape(steps),
        "images": np.asarray(record["steps/observation/image"]).reshape(steps),
    }
    arrays["instruction"] = decode_instruction(record, steps)
    arrays["steps"] = steps
    return arrays


def export_selected(source: Path, out: Path, selected: list[EpisodeProfile], fps: int) -> None:
    selected_ids = {item.source_id for item in selected}
    dataset = LeRobotDataset.create(
        REPO_ID,
        fps=fps,
        root=out,
        robot_type="xarm_ucsd_kitchen",
        features=feature_contract(),
        use_videos=True,
        image_writer_threads=8,
        image_writer_processes=0,
        data_files_size_in_mb=256,
        video_files_size_in_mb=512,
    )
    exported = 0
    for shard in complete_shards(source):
        for record_index, record in enumerate(tfrecord_loader(str(shard), None)):
            source_id = f"{shard.name}:{record_index}"
            if source_id not in selected_ids:
                continue
            episode = reshape_record(record)
            for step in range(episode["steps"]):
                image = np.asarray(Image.open(io.BytesIO(bytes(episode["images"][step]))).convert("RGB"))
                if image.shape != (480, 640, 3):
                    raise RuntimeError(f"Unexpected image shape for {source_id}: {image.shape}")
                dataset.add_frame({
                    "observation.state": episode["state"][step],
                    "observation.images.rgb": image,
                    "action": episode["action"][step],
                    "reward": np.array([episode["reward"][step]], dtype=np.float32),
                    "discount": np.array([episode["discount"][step]], dtype=np.float32),
                    "done": np.array([episode["done"][step]], dtype=bool),
                    "task": episode["instruction"],
                })
            dataset.save_episode()
            exported += 1
    dataset.finalize()
    if exported != len(selected):
        raise RuntimeError(f"Selected {len(selected)} episodes but exported {exported}")


def validate_dataset(out: Path, selected: list[EpisodeProfile], fps: int) -> dict:
    metadata = LeRobotDatasetMetadata(REPO_ID, root=out)
    dataset = LeRobotDataset(REPO_ID, root=out, return_uint8=True)
    expected_frames = sum(item.steps for item in selected)
    checks = {
        "official_metadata_load": metadata.total_episodes == len(selected),
        "episode_count": int(metadata.total_episodes),
        "frame_count": int(metadata.total_frames),
        "expected_frame_count": expected_frames,
        "frame_count_matches": int(metadata.total_frames) == expected_frames,
        "fps": int(metadata.fps),
        "fps_matches": int(metadata.fps) == fps,
        "robot_type": metadata.robot_type,
        "camera_keys": list(metadata.camera_keys),
    }
    sample_indices = sorted({0, len(dataset) // 2, len(dataset) - 1})
    sample_shapes = []
    for sample_index in sample_indices:
        sample = dataset[sample_index]
        state = sample["observation.state"]
        action = sample["action"]
        image = sample["observation.images.rgb"]
        if state.shape != torch.Size([21]) or action.shape != torch.Size([8]) or image.shape != torch.Size([3, 480, 640]):
            raise RuntimeError(f"Official loader returned invalid sample shapes at {sample_index}")
        if not torch.isfinite(state).all() or not torch.isfinite(action).all():
            raise RuntimeError(f"Non-finite training tensor at {sample_index}")
        sample_shapes.append({
            "index": sample_index,
            "state": list(state.shape),
            "action": list(action.shape),
            "image": list(image.shape),
        })
    batch = next(iter(DataLoader(dataset, batch_size=4, shuffle=False, num_workers=0)))
    if tuple(batch["action"].shape) != (4, 8):
        raise RuntimeError(f"Training DataLoader batch shape mismatch: {batch['action'].shape}")
    first_image = dataset[0]["observation.images.rgb"].permute(1, 2, 0).cpu().numpy()
    Image.fromarray(first_image.astype(np.uint8)).save(out / "sample_playback.png")
    checks.update({
        "official_sample_playback": True,
        "sample_shapes": sample_shapes,
        "dataloader_batch_action_shape": list(batch["action"].shape),
        "schema_validation_passed": all([
            checks["official_metadata_load"],
            checks["frame_count_matches"],
            checks["fps_matches"],
        ]),
    })
    return checks


def write_evidence(out: Path, source: Path, shards: list[Path], selected: list[EpisodeProfile], validation: dict) -> dict:
    index_path = out / "trajectory_index.jsonl"
    with index_path.open("w", encoding="utf-8") as handle:
        for episode_index, profile in enumerate(selected):
            handle.write(json.dumps({"episode_index": episode_index, **asdict(profile)}, ensure_ascii=False) + "\n")

    artifact_files = sorted(
        path
        for path in out.rglob("*")
        if path.is_file() and path.name not in {"package_manifest.json", "gate1_acceptance_report.json"}
    )
    file_entries = [
        {
            "path": str(path.relative_to(out)),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in artifact_files
    ]
    manifest = {
        "product": "qtail_gate1_lerobot_v3_trajectory_adapter",
        "format": "LeRobotDataset v3.0",
        "source_format": "Open X Embodiment RLDS TFRecord",
        "source_dataset": DATASET_NAME,
        "source_root": str(source),
        "generated_at": now(),
        "selection_method": "Q-Tail deterministic risk + instruction rarity + Porter-Thomas ranking",
        "trajectory_count": len(selected),
        "frame_count": validation["frame_count"],
        "files": file_entries,
        "total_bytes": sum(item["bytes"] for item in file_entries),
        "claim_boundary": [
            "The exported episodes are real Open X trajectories converted into LeRobot v3, not newly synthesized trajectories.",
            "This validates the RLDS-to-LeRobot production adapter and training loader, not buyer-specific robot execution.",
            "Closed-loop policy uplift and real-robot procurement evidence belong to Gate 2 and Gate 3.",
        ],
    }
    manifest_path = out / "package_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest_sha256 = sha256_file(manifest_path)
    report = {
        "gate": 1,
        "status": "passed_adapter_baseline",
        "generated_at": now(),
        "trajectory_count": len(selected),
        "source_episode_count": sum(1 for _ in selected),
        "complete_source_shards": len(shards),
        "schema_validation_passed": bool(validation["schema_validation_passed"]),
        "sample_playback_passed": bool(validation["official_sample_playback"]),
        "training_dataloader_passed": validation["dataloader_batch_action_shape"] == [4, 8],
        "package_manifest_sha256": manifest_sha256,
        "manifest": str(manifest_path),
        "validation": validation,
        "evidence_level": "local production-adapter baseline using real public trajectories",
        "buyer_gate_status": "requires buyer-specific backend/operator review before production approval",
    }
    report_path = out / "gate1_acceptance_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and validate the Q-Tail Gate 1 LeRobot v3 trajectory package.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--episodes", type=int, default=64)
    parser.add_argument("--fps", type=int, default=10, help="Normalized export rate used for LeRobot timestamps.")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if args.episodes < 1:
        raise SystemExit("--episodes must be positive")
    if args.fps < 1:
        raise SystemExit("--fps must be positive")
    source = args.source.resolve()
    out = args.out.resolve()
    shards = complete_shards(source)
    if not shards:
        raise SystemExit(f"No complete TFRecord shards found under {source}")
    if out.exists():
        if not args.overwrite:
            raise SystemExit(f"Output exists: {out}; pass --overwrite to replace it")
        shutil.rmtree(out)
    profiles = score_profiles(scan_profiles(shards))
    selected = profiles[: min(args.episodes, len(profiles))]
    export_selected(source, out, selected, args.fps)
    validation = validate_dataset(out, selected, args.fps)
    report = write_evidence(out, source, shards, selected, validation)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
