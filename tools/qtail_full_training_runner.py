#!/usr/bin/env python3
"""Full trajectory download/training runner for Q-Tail validation.

This script is intentionally strict: it does not claim full-training results
unless real full-trajectory data is present and a training backend has run.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = ROOT / "external_data" / "embodied_full"
DEFAULT_RUN_ROOT = ROOT / "results" / "qtail_full_training"

DROID_GCS_PREFIX = "gs://gresearch/robotics/droid"
DROID_TFDS_SNIPPET = 'tfds.load("droid", data_dir="gs://gresearch/robotics", split="train")'
OPENX_GCS_PREFIX = "gs://gdm-robotics-open-x-embodiment"
EXTRA_BIN_DIRS = [Path.home() / "Library" / "Python" / f"{sys.version_info.major}.{sys.version_info.minor}" / "bin"]


def command_exists(name: str) -> bool:
    return command_path(name) is not None


def command_path(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for directory in EXTRA_BIN_DIRS:
        candidate = directory / name
        if candidate.exists():
            return str(candidate)
    return None


def module_exists(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


def run_command(cmd: list[str], *, dry_run: bool, cwd: Path | None = None) -> dict:
    if dry_run:
        return {"cmd": cmd, "dry_run": True, "returncode": None}
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, capture_output=True)
    return {
        "cmd": cmd,
        "dry_run": False,
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout[-4000:],
        "stderr_tail": proc.stderr[-4000:],
    }


def gsutil_du(uri: str) -> dict:
    gsutil = command_path("gsutil")
    if not gsutil:
        return {"uri": uri, "status": "blocked", "reason": "missing gsutil"}
    proc = subprocess.run([gsutil, "du", "-s", uri], text=True, capture_output=True)
    result = {"uri": uri, "returncode": proc.returncode, "stdout": proc.stdout.strip(), "stderr": proc.stderr.strip()}
    if proc.returncode == 0 and proc.stdout.strip():
        try:
            byte_count = int(proc.stdout.split()[0])
            result["bytes"] = byte_count
            result["tib"] = round(byte_count / (1024**4), 3)
        except Exception:
            pass
    return result


def preflight(data_root: Path) -> dict:
    stat = shutil.disk_usage(data_root.parent if data_root.parent.exists() else ROOT)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_root": str(data_root),
        "disk_free_bytes": stat.free,
        "disk_free_gib": round(stat.free / (1024**3), 2),
        "disk_free_tib": round(stat.free / (1024**4), 3),
        "tools": {
            "gsutil": command_exists("gsutil"),
            "gcloud": command_exists("gcloud"),
            "huggingface-cli": command_exists("huggingface-cli"),
            "git": command_exists("git"),
        },
        "python_modules": {
            "tensorflow": module_exists("tensorflow"),
            "tensorflow_datasets": module_exists("tensorflow_datasets"),
            "torch": module_exists("torch"),
            "rlds": module_exists("rlds"),
        },
        "official_access": {
            "droid_full_gsutil": f"gsutil -m cp -r {DROID_GCS_PREFIX} {data_root}/",
            "droid_tfds": DROID_TFDS_SNIPPET,
            "openx_manual_gsutil": f"gsutil -m cp -r {OPENX_GCS_PREFIX}/{{dataset_name}} ~/tensorflow_datasets/",
            "openx_repo": "https://github.com/google-deepmind/open_x_embodiment",
            "droid_policy_repo": "https://github.com/droid-dataset/droid_policy_learning",
        },
        "known_full_dataset_size_probe": {
            "droid": gsutil_du(DROID_GCS_PREFIX),
        },
    }


def download_droid_tfds(data_root: Path, *, dry_run: bool) -> dict:
    target = data_root / "tfds"
    target.mkdir(parents=True, exist_ok=True)
    code = (
        "import tensorflow_datasets as tfds\n"
        f"builder = tfds.builder('droid', data_dir={str(target)!r})\n"
        "builder.download_and_prepare()\n"
        "print(builder.info)\n"
    )
    return run_command([sys.executable, "-c", code], dry_run=dry_run)


def download_droid_gsutil(data_root: Path, *, dry_run: bool) -> dict:
    target = data_root / "droid_full"
    target.mkdir(parents=True, exist_ok=True)
    gsutil = command_path("gsutil") or "gsutil"
    return run_command([gsutil, "-m", "cp", "-r", DROID_GCS_PREFIX, str(target)], dry_run=dry_run)


def droid_disk_blocker(preflight_result: dict, slack: float = 1.05) -> dict | None:
    droid_probe = preflight_result.get("known_full_dataset_size_probe", {}).get("droid", {})
    required_bytes = droid_probe.get("bytes")
    free_bytes = preflight_result.get("disk_free_bytes")
    if not required_bytes or not free_bytes:
        return None
    required_with_slack = int(required_bytes * slack)
    if free_bytes < required_with_slack:
        return {
            "dataset": "droid",
            "status": "blocked",
            "reason": "insufficient_disk_for_full_droid",
            "official_source": DROID_GCS_PREFIX,
            "required_tib": round(required_with_slack / (1024**4), 3),
            "dataset_tib": droid_probe.get("tib"),
            "free_tib": preflight_result.get("disk_free_tib"),
        }
    return None


def download_openx_dataset(dataset_name: str, data_root: Path, *, dry_run: bool) -> dict:
    target = data_root / "tensorflow_datasets"
    target.mkdir(parents=True, exist_ok=True)
    gsutil = command_path("gsutil") or "gsutil"
    return run_command(
        [gsutil, "-m", "cp", "-r", f"{OPENX_GCS_PREFIX}/{dataset_name}", str(target)],
        dry_run=dry_run,
    )


def clone_training_backends(data_root: Path, *, dry_run: bool) -> list[dict]:
    repos = [
        ("open_x_embodiment", "https://github.com/google-deepmind/open_x_embodiment"),
        ("droid_policy_learning", "https://github.com/droid-dataset/droid_policy_learning"),
    ]
    backend_root = data_root / "training_backends"
    backend_root.mkdir(parents=True, exist_ok=True)
    results = []
    for name, url in repos:
        dst = backend_root / name
        if dst.exists():
            results.append({"repo": url, "path": str(dst), "status": "already_exists"})
        else:
            results.append(run_command(["git", "clone", url, str(dst)], dry_run=dry_run))
    return results


def write_plan(args: argparse.Namespace, preflight_result: dict, actions: list[dict]) -> Path:
    args.out.mkdir(parents=True, exist_ok=True)
    plan = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": args.mode,
        "dataset": args.dataset,
        "claim_boundary": [
            "No full-training result is valid until full trajectories are downloaded and a policy-training backend completes.",
            "Q-Tail must be compared against the original allocation with identical model, compute, training steps, environment, and evaluator.",
            "This runner records commands and preflight state so failed/incomplete full-training attempts cannot be mistaken for results.",
        ],
        "preflight": preflight_result,
        "actions": actions,
    }
    path = args.out / "full_training_run_manifest.json"
    path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Download full embodied datasets and prepare full Q-Tail training validation.")
    parser.add_argument("--dataset", choices=["droid", "openx", "both"], default="both")
    parser.add_argument("--mode", choices=["preflight", "download", "clone-backends"], default="preflight")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--out", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--openx-dataset", action="append", default=[], help="Open X dataset name under gs://gdm-robotics-open-x-embodiment.")
    parser.add_argument("--execute", action="store_true", help="Actually run download/clone commands. Omit for dry-run manifest.")
    args = parser.parse_args()

    args.data_root.mkdir(parents=True, exist_ok=True)
    pf = preflight(args.data_root)
    actions: list[dict] = []
    dry_run = not args.execute

    if args.mode == "download":
        if args.dataset in {"droid", "both"}:
            disk_blocker = droid_disk_blocker(pf)
            if disk_blocker:
                actions.append(disk_blocker)
            elif pf["tools"]["gsutil"]:
                actions.append(download_droid_gsutil(args.data_root, dry_run=dry_run))
            elif not pf["python_modules"]["tensorflow_datasets"]:
                actions.append({"dataset": "droid", "status": "blocked", "reason": "missing gsutil and tensorflow_datasets"})
            else:
                actions.append(download_droid_tfds(args.data_root, dry_run=dry_run))
        if args.dataset in {"openx", "both"}:
            if not pf["tools"]["gsutil"]:
                actions.append({"dataset": "openx", "status": "blocked", "reason": "missing gsutil"})
            elif not args.openx_dataset:
                actions.append({"dataset": "openx", "status": "blocked", "reason": "provide --openx-dataset NAME; full Open X is many TFDS datasets"})
            else:
                for dataset_name in args.openx_dataset:
                    actions.append(download_openx_dataset(dataset_name, args.data_root, dry_run=dry_run))
    elif args.mode == "clone-backends":
        actions.extend(clone_training_backends(args.data_root, dry_run=dry_run))
    else:
        actions.append({"status": "preflight_only"})

    manifest = write_plan(args, pf, actions)
    print(json.dumps({"manifest": str(manifest), "preflight": pf, "actions": actions}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
