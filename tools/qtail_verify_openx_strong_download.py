#!/usr/bin/env python3
"""Verify that the Open X Strong add-on is complete enough for final training."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "data" / "openx_demo"
DEFAULT_OUT = ROOT / "results" / "openx_strong_download" / "strong_download_verification.json"
EXPECTED_DATASETS = {
    "language_table": {
        "min_gib": 46.0,
        "min_tfrecords": 60,
        "required_files": ["features.json", "dataset_info.json"],
    },
    "language_table_sim": {
        "min_gib": 80.0,
        "min_tfrecords": 20,
        "required_files": ["features.json", "dataset_info.json"],
    },
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_partial_download(path: Path) -> bool:
    return ".gstmp" in path.name or path.name.endswith(".tmp") or path.name.endswith(".part")


def file_size_sum(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for item in path.rglob("*"):
        if item.is_file() and not is_partial_download(item):
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return total


def dataset_status(data_dir: Path, name: str, expected: dict) -> dict:
    path = data_dir / name
    all_files = list(path.rglob("*")) if path.exists() else []
    tfrecords = [item for item in all_files if item.is_file() and "tfrecord" in item.name and not is_partial_download(item)]
    partials = [item for item in all_files if item.is_file() and is_partial_download(item)]
    bytes_total = file_size_sum(path)
    required = []
    for filename in expected["required_files"]:
        required.extend([item for item in all_files if item.is_file() and item.name == filename])
    errors = []
    if not path.exists():
        errors.append("dataset_dir_missing")
    if bytes_total < expected["min_gib"] * (1024**3):
        errors.append("below_min_gib")
    if len(tfrecords) < expected["min_tfrecords"]:
        errors.append("below_min_tfrecord_count")
    if len(required) < len(expected["required_files"]):
        errors.append("missing_required_metadata")
    if partials:
        errors.append("partial_gsutil_files_present")
    return {
        "dataset": name,
        "path": str(path),
        "exists": path.exists(),
        "bytes": bytes_total,
        "gib": round(bytes_total / (1024**3), 3),
        "tfrecord_count": len(tfrecords),
        "partial_file_count": len(partials),
        "required_metadata_found": sorted({item.name for item in required}),
        "expected": expected,
        "valid": not errors,
        "errors": errors,
    }


def verify(data_dir: Path) -> dict:
    datasets = [dataset_status(data_dir, name, expected) for name, expected in EXPECTED_DATASETS.items()]
    errors = []
    for item in datasets:
        errors.extend([f"{item['dataset']}:{error}" for error in item["errors"]])
    return {
        "generated_at": now(),
        "data_dir": str(data_dir),
        "ready_for_strong_training": not errors,
        "errors": errors,
        "datasets": datasets,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify Open X Strong add-on download before final training.")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--require-ready", action="store_true", help="Exit non-zero unless Strong data is complete.")
    args = parser.parse_args()

    payload = verify(Path(args.data_dir))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if args.require_ready and not payload["ready_for_strong_training"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
