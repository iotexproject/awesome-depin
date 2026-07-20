#!/usr/bin/env python3
"""Refresh Q-Tail incremental training and service package when data grows."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from qtail_train_openx_demo import dataset_name, find_shards


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "openx_demo"
STATUS_DIR = ROOT / "results" / "qtail_auto_refresh"
STATUS_PATH = STATUS_DIR / "refresh_status.json"
TRAINING_LEDGER_PATH = STATUS_DIR / "training_ledger.json"
INCREMENTAL_OUT = ROOT / "results" / "openx_incremental_training_snapshot"
SERVICE_OUT = ROOT / "results" / "qtail_openx_service_public"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def training_input_summary(path: Path) -> dict:
    shards = find_shards(path) if path.exists() else []
    total_bytes = 0
    datasets = set()
    for shard in shards:
        total_bytes += shard.stat().st_size
        datasets.add(dataset_name(shard, path))
    return {
        "bytes": total_bytes,
        "gib": round(total_bytes / (1024**3), 3),
        "shard_count": len(shards),
        "dataset_count": len(datasets),
        "datasets": sorted(datasets),
    }


def load_status() -> dict:
    if not STATUS_PATH.exists():
        return {}
    try:
        return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_status(payload: dict) -> None:
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def append_training_ledger(status: dict) -> None:
    report = load_json(INCREMENTAL_OUT / "openx_demo_training_report.json")
    service = load_json(SERVICE_OUT / "qtail_service_delivery_report.json")
    effect = report.get("effect_metrics") or {}
    service_effect = service.get("effect_summary") or {}
    row = {
        "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "generated_at": now(),
        "byte_policy": status.get("byte_policy"),
        "force": status.get("force"),
        "trainable_gib": report.get("total_gib"),
        "shard_count": report.get("shard_count"),
        "steps": report.get("steps"),
        "dataset_count": len(report.get("datasets") or []),
        "datasets": report.get("datasets") or [],
        "source_pred_tail_share": effect.get("source_pred_tail_share"),
        "qtail_pred_tail_share": effect.get("qtail_pred_tail_share"),
        "predicted_tail_share_gain_pp": effect.get("predicted_tail_share_gain_pp"),
        "consistent_with_pt_tail_goal": effect.get("consistent_with_pt_tail_goal"),
        "service_tail_success_gain_pp": service_effect.get("tail_success_gain_pp"),
        "service_tail_success_relative_gain_pct": service_effect.get("tail_success_relative_gain_pct"),
        "service_cvar20_gain_pp": service_effect.get("cvar20_gain_pp"),
        "service_tail_data_share_gain_pp": service_effect.get("tail_data_share_gain_pp"),
        "service_winner": (service_effect.get("decision") or {}).get("winner"),
        "service_passed": (service_effect.get("decision") or {}).get("passed"),
        "incremental_report": str(INCREMENTAL_OUT / "openx_demo_training_report.json"),
        "training_rows": str(INCREMENTAL_OUT / "openx_shard_training_rows.csv"),
        "service_delivery_report": str(SERVICE_OUT / "qtail_service_delivery_report.json"),
        "service_package_zip": service.get("package_zip"),
    }
    payload = {"rows": []}
    if TRAINING_LEDGER_PATH.exists():
        payload = load_json(TRAINING_LEDGER_PATH) or payload
        if not isinstance(payload.get("rows"), list):
            payload["rows"] = []
    dedupe_key = (
        row.get("trainable_gib"),
        row.get("shard_count"),
        row.get("steps"),
        row.get("byte_policy"),
    )
    if payload["rows"]:
        last = payload["rows"][-1]
        last_key = (
            last.get("trainable_gib"),
            last.get("shard_count"),
            last.get("steps"),
            last.get("byte_policy"),
        )
        if last_key == dedupe_key:
            payload["rows"][-1] = row
        else:
            payload["rows"].append(row)
    else:
        payload["rows"].append(row)
    payload["rows"] = payload["rows"][-120:]
    payload["generated_at"] = now()
    payload["row_count"] = len(payload["rows"])
    TRAINING_LEDGER_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run_step(command: list[str], log_path: Path) -> dict:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = now()
    proc = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    log_path.write_text(
        f"$ {' '.join(command)}\n\nSTDOUT:\n{proc.stdout}\n\nSTDERR:\n{proc.stderr}\n",
        encoding="utf-8",
    )
    return {
        "command": command,
        "started_at": started,
        "finished_at": now(),
        "returncode": proc.returncode,
        "log": str(log_path),
    }


def previous_refreshed_shard_count(previous: dict) -> int:
    if previous.get("last_refreshed_shard_count") is not None:
        try:
            return int(previous.get("last_refreshed_shard_count") or 0)
        except Exception:
            pass
    report = load_json(INCREMENTAL_OUT / "openx_demo_training_report.json")
    try:
        return int(report.get("shard_count") or 0)
    except Exception:
        return 0


def refresh(*, force: bool, min_growth_gib: float, min_new_shards: int, steps: int) -> dict:
    previous = load_status()
    current_input = training_input_summary(DATA_DIR)
    current_bytes = current_input["bytes"]
    current_shards = int(current_input["shard_count"])
    previous_bytes = int(previous.get("last_refreshed_bytes") or 0)
    previous_shards = previous_refreshed_shard_count(previous)
    raw_growth_bytes = current_bytes - previous_bytes
    growth_bytes = max(raw_growth_bytes, 0)
    raw_shard_growth = current_shards - previous_shards
    shard_growth = max(raw_shard_growth, 0)
    threshold_bytes = int(min_growth_gib * (1024**3))
    should_refresh = bool(
        force
        or not previous
        or growth_bytes >= threshold_bytes
        or shard_growth >= min_new_shards
    )
    trigger_reasons = []
    if force:
        trigger_reasons.append("force")
    if not previous:
        trigger_reasons.append("no_previous_status")
    if growth_bytes >= threshold_bytes:
        trigger_reasons.append("byte_growth_threshold")
    if shard_growth >= min_new_shards:
        trigger_reasons.append("new_complete_shard_threshold")
    status = {
        "generated_at": now(),
        "data_dir": str(DATA_DIR),
        "current_bytes": current_bytes,
        "current_gib": current_input["gib"],
        "current_shard_count": current_shards,
        "current_dataset_count": current_input["dataset_count"],
        "current_datasets": current_input["datasets"],
        "last_refreshed_bytes": previous_bytes,
        "last_refreshed_shard_count": previous_shards,
        "raw_growth_bytes": raw_growth_bytes,
        "raw_shard_growth": raw_shard_growth,
        "growth_bytes": growth_bytes,
        "growth_gib": round(growth_bytes / (1024**3), 3),
        "shard_growth": shard_growth,
        "byte_policy": "complete_files_only_excluding_gstmp_tmp_part",
        "baseline_adjusted": raw_growth_bytes < 0,
        "min_growth_gib": min_growth_gib,
        "min_new_shards": min_new_shards,
        "refresh_requested": should_refresh,
        "trigger_reasons": trigger_reasons,
        "force": force,
        "steps": steps,
        "steps_ran": [],
        "previous_status": previous.get("status"),
        "last_refreshed_at": previous.get("last_refreshed_at"),
        "last_refreshed_gib": previous.get("last_refreshed_gib"),
        "last_refreshed_shards": previous.get("last_refreshed_shard_count") or previous_shards,
        "incremental_report": previous.get("incremental_report"),
        "service_delivery_report": previous.get("service_delivery_report"),
    }
    write_status(status)
    if not should_refresh:
        status["status"] = "skipped_waiting_for_more_data"
        write_status(status)
        return status

    train = run_step(
        [
            "python3",
            "tools/qtail_train_openx_demo.py",
            "--data-dir",
            str(DATA_DIR),
            "--out",
            str(INCREMENTAL_OUT),
            "--steps",
            str(steps),
            "--wait",
            "0",
            "--min-shards",
            "12",
            "--records-per-shard",
            "1",
            "--min-record-parse-rate",
            "0.95",
        ],
        STATUS_DIR / "incremental_train.log",
    )
    status["steps_ran"].append(train)
    if train["returncode"] != 0:
        status["status"] = "failed_incremental_training"
        write_status(status)
        return status

    service = run_step(
        [
            "python3",
            "tools/qtail_openx_service_model.py",
            "--input",
            "data/embodied_public_anchor_real.csv",
            "--out",
            str(SERVICE_OUT),
            "--training-report",
            str(INCREMENTAL_OUT / "openx_demo_training_report.json"),
            "--training-rows",
            str(INCREMENTAL_OUT / "openx_shard_training_rows.csv"),
            "--top-k",
            "128",
            "--synthetic-budget",
            "100000",
        ],
        STATUS_DIR / "service_rebuild.log",
    )
    status["steps_ran"].append(service)
    if service["returncode"] != 0:
        status["status"] = "failed_service_rebuild"
        write_status(status)
        return status

    status.update({
        "status": "refreshed",
        "last_refreshed_at": now(),
        "last_refreshed_bytes": current_bytes,
        "last_refreshed_gib": current_input["gib"],
        "last_refreshed_shard_count": current_shards,
        "last_refreshed_shards": current_shards,
        "incremental_report": str(INCREMENTAL_OUT / "openx_demo_training_report.json"),
        "service_delivery_report": str(SERVICE_OUT / "qtail_service_delivery_report.json"),
    })
    append_training_ledger(status)
    write_status(status)

    manifest = run_step(
        ["python3", "tools/qtail_openx_progress_manifest.py"],
        STATUS_DIR / "manifest_refresh.log",
    )
    status["steps_ran"].append(manifest)
    if manifest["returncode"] != 0:
        status["status"] = "failed_manifest_refresh"
        write_status(status)
        return status

    write_status(status)
    return status


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh Q-Tail Open X incremental model when downloaded data grows.")
    parser.add_argument("--force", action="store_true", help="Run refresh regardless of growth threshold.")
    parser.add_argument("--min-growth-gib", type=float, default=2.0, help="Minimum data growth needed to retrain.")
    parser.add_argument("--min-new-shards", type=int, default=1, help="Minimum complete shard growth needed to retrain.")
    parser.add_argument("--steps", type=int, default=2500, help="Incremental training steps.")
    args = parser.parse_args()
    print(json.dumps(
        refresh(
            force=args.force,
            min_growth_gib=args.min_growth_gib,
            min_new_shards=args.min_new_shards,
            steps=args.steps,
        ),
        indent=2,
        ensure_ascii=False,
    ))


if __name__ == "__main__":
    main()
