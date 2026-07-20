#!/usr/bin/env python3
"""Build a page-facing progress manifest for Open X Q-Tail training."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "openx_demo"
OUT_DIR = ROOT / "results" / "openx_training_progress"
TARGET_DEMO_GIB = 31.63
TARGET_STRONG_GIB = 171.62
LOCAL_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


def local_iso() -> str:
    return datetime.now(LOCAL_TZ).isoformat()


def run(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def du_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return total


def is_partial_download(path: Path) -> bool:
    return ".gstmp" in path.name or path.name.endswith(".tmp") or path.name.endswith(".part")


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_text_file(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        return None


def read_tail_text(path: Path, max_bytes: int = 256 * 1024) -> str:
    if not path.exists():
        return ""
    try:
        with path.open("rb") as handle:
            size = path.stat().st_size
            handle.seek(max(size - max_bytes, 0))
            return handle.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def compact_log_line(line: str, max_chars: int = 220) -> str:
    line = line.strip(" -\\|/\r\t")
    if not line:
        return ""
    # gsutil rewrites progress with carriage returns; keep the latest readable
    # fragment so the progress page does not render huge terminal buffers.
    if "\r" in line:
        line = line.split("\r")[-1]
    line = re.sub(r"\s+", " ", line).strip()
    if len(line) <= max_chars:
        return line
    return line[: max_chars - 3] + "..."


def log_tail(path: Path, n: int = 60) -> list[str]:
    text = read_tail_text(path)
    if not text:
        return []
    lines = []
    for raw in text.replace("\r", "\n").splitlines():
        line = compact_log_line(raw)
        if line:
            lines.append(line)
    return lines[-n:]


def log_age_seconds(path: Path) -> float | None:
    if not path.exists():
        return None
    try:
        return max(0.0, datetime.now(timezone.utc).timestamp() - path.stat().st_mtime)
    except OSError:
        return None


def latest_gsutil_progress(path: Path) -> dict:
    text = read_tail_text(path, max_bytes=4 * 1024 * 1024)
    if not text:
        return {}
    text = text.replace("\r", "\n")
    active_dataset = None
    latest_progress = {}
    start_pattern = re.compile(r"START\s+([A-Za-z0-9_./-]+)\s+gs://")
    progress_pattern = re.compile(
        r"\[(\d+)/(\d+)\s+files\]\[\s*([0-9.]+)\s+(KiB|MiB|GiB)/\s*([0-9.]+)\s+(KiB|MiB|GiB)\]\s+(\d+)%\s+Done\s*(.*?)\s*(?:ETA\s+([0-9:+A-Za-z ]+))?$"
    )
    unit_scale = {"KiB": 1 / (1024 * 1024), "MiB": 1 / 1024, "GiB": 1}
    for raw in text.splitlines():
        line = raw.strip(" -\\|/")
        start = start_pattern.search(line)
        if start:
            active_dataset = start.group(1)
        match = progress_pattern.search(line)
        if match:
            done_files = int(match.group(1))
            total_files = int(match.group(2))
            done_gib = float(match.group(3)) * unit_scale[match.group(4)]
            total_gib = float(match.group(5)) * unit_scale[match.group(6)]
            latest_progress = {
                "active_dataset": active_dataset,
                "files_done": done_files,
                "files_total": total_files,
                "done_gib": round(done_gib, 3),
                "total_gib": round(total_gib, 3),
                "percent": int(match.group(7)),
                "speed": match.group(8).strip(),
                "eta": (match.group(9) or "").strip(),
                "line": raw.strip(),
            }
    latest_progress["log_age_seconds"] = log_age_seconds(path)
    latest_progress["fresh"] = (
        latest_progress.get("log_age_seconds") is not None
        and latest_progress["log_age_seconds"] < 15 * 60
    )
    process_text = run(["ps", "-axo", "command"])
    running_datasets = []
    for line in process_text.splitlines():
        if "gsutil" not in line or "gdm-robotics-open-x-embodiment/" not in line:
            continue
        match = re.search(r"gdm-robotics-open-x-embodiment/([A-Za-z0-9_./-]+)", line)
        if match:
            running_datasets.append(match.group(1).rstrip("/"))
    if running_datasets:
        latest_progress["active_dataset"] = running_datasets[-1]
    return latest_progress


def latest_gsutil_config(path: Path) -> dict:
    text = read_tail_text(path, max_bytes=2 * 1024 * 1024)
    config = {}
    pattern = re.compile(
        r"\[(?P<ts>[^\]]+)\]\s+gsutil_config\s+processes=(?P<processes>\S+)\s+threads=(?P<threads>\S+)\s+sliced_threshold=(?P<threshold>\S+)\s+sliced_components=(?P<components>\S+)"
    )
    for line in text.replace("\r", "\n").splitlines():
        match = pattern.search(line)
        if not match:
            continue
        config = {
            "generated_at": match.group("ts"),
            "parallel_process_count": match.group("processes"),
            "parallel_thread_count": match.group("threads"),
            "sliced_object_download_threshold": match.group("threshold"),
            "sliced_object_download_max_components": match.group("components"),
            "line": line.strip(),
            "policy": "Use one process on macOS, higher thread concurrency, and sliced object downloads for large RLDS TFRecord shards.",
        }
    return config


def disk_status(total_bytes: int) -> dict:
    usage = shutil.disk_usage(DATA_DIR if DATA_DIR.exists() else ROOT)
    free_gib = usage.free / (1024**3)
    remaining_strong_gib = max(TARGET_STRONG_GIB - (total_bytes / (1024**3)), 0.0)
    projected_free_after_strong_gib = free_gib - remaining_strong_gib
    if projected_free_after_strong_gib >= 50:
        safety = "ok"
    elif projected_free_after_strong_gib >= 20:
        safety = "watch"
    else:
        safety = "risk"
    return {
        "path": str(DATA_DIR if DATA_DIR.exists() else ROOT),
        "total_gib": round(usage.total / (1024**3), 3),
        "used_gib": round(usage.used / (1024**3), 3),
        "free_gib": round(free_gib, 3),
        "target_strong_gib": TARGET_STRONG_GIB,
        "remaining_to_strong_target_gib": round(remaining_strong_gib, 3),
        "projected_free_after_strong_gib": round(projected_free_after_strong_gib, 3),
        "safety": safety,
    }


def speed_to_bytes_per_second(speed: object) -> float | None:
    if not speed:
        return None
    match = re.search(r"([0-9.]+)\s*(KiB|MiB|GiB)/s", str(speed))
    if not match:
        return None
    value = float(match.group(1))
    scale = {"KiB": 1024, "MiB": 1024**2, "GiB": 1024**3}[match.group(2)]
    return value * scale


def seconds_for_gib(gib: float | None, bytes_per_second: float | None) -> float | None:
    if gib is None or gib <= 0 or not bytes_per_second or bytes_per_second <= 0:
        return None
    return gib * (1024**3) / bytes_per_second


def gate_forecast(
    *,
    total_gib: float,
    trainable_gib: float,
    download_progress: dict,
    refresh: dict,
    strong_verification: dict,
) -> dict:
    bytes_per_second = speed_to_bytes_per_second(download_progress.get("speed"))
    current_dataset_remaining_gib = None
    if download_progress.get("total_gib") is not None and download_progress.get("done_gib") is not None:
        current_dataset_remaining_gib = max(
            float(download_progress.get("total_gib") or 0) - float(download_progress.get("done_gib") or 0),
            0.0,
        )
    refresh_remaining_gib = float(refresh.get("remaining_to_next_refresh_gib") or 0)
    strong_remaining_trainable_gib = max(TARGET_STRONG_GIB - trainable_gib, 0.0)
    disk_vs_trainable_gap_gib = max(total_gib - trainable_gib, 0.0)
    return {
        "speed": download_progress.get("speed"),
        "bytes_per_second": round(bytes_per_second, 3) if bytes_per_second else None,
        "current_dataset_remaining_gib": round(current_dataset_remaining_gib, 3)
        if current_dataset_remaining_gib is not None
        else None,
        "eta_current_dataset_seconds": seconds_for_gib(current_dataset_remaining_gib, bytes_per_second),
        "next_incremental_refresh_remaining_gib": round(refresh_remaining_gib, 3),
        "eta_next_incremental_refresh_seconds": seconds_for_gib(refresh_remaining_gib, bytes_per_second),
        "strong_remaining_trainable_gib": round(strong_remaining_trainable_gib, 3),
        "eta_strong_target_seconds_at_current_speed": seconds_for_gib(strong_remaining_trainable_gib, bytes_per_second),
        "disk_vs_trainable_gap_gib": round(disk_vs_trainable_gap_gib, 3),
        "strong_ready": bool(strong_verification.get("ready_for_strong_training")),
        "forecast_boundary": "ETA uses the latest gsutil transfer speed and is not a guarantee; training still requires strong verification to pass.",
    }


def strong_dataset_completion(strong_verification: dict) -> list[dict]:
    rows = []
    for item in strong_verification.get("datasets") or []:
        expected = item.get("expected") or {}
        min_gib = float(expected.get("min_gib") or 0)
        min_tfrecords = int(expected.get("min_tfrecords") or 0)
        gib = float(item.get("gib") or 0)
        tfrecords = int(item.get("tfrecord_count") or 0)
        rows.append({
            "dataset": item.get("dataset"),
            "valid": bool(item.get("valid")),
            "gib": gib,
            "min_gib": min_gib,
            "gib_completion_pct": (gib / min_gib * 100.0) if min_gib else None,
            "remaining_gib": max(min_gib - gib, 0.0),
            "tfrecord_count": tfrecords,
            "min_tfrecords": min_tfrecords,
            "tfrecord_completion_pct": (tfrecords / min_tfrecords * 100.0) if min_tfrecords else None,
            "remaining_tfrecords": max(min_tfrecords - tfrecords, 0),
            "partial_file_count": item.get("partial_file_count"),
            "errors": item.get("errors") or [],
        })
    return rows


def submission_summary(
    *,
    incremental_report: dict,
    service_delivery: dict,
    strong_verification: dict,
    strong_pipeline: dict,
    training_quality: dict,
    refresh: dict,
    latest_api: dict,
) -> dict:
    incremental_effect = incremental_report.get("effect_metrics", {})
    service_effect = service_delivery.get("effect_summary", {})
    latest_api_effect = latest_api.get("effect_summary", {})
    return {
        "status": "ready_as_incremental_evidence"
        if training_quality.get("clean") and service_effect.get("decision", {}).get("passed")
        else "needs_review",
        "can_claim": [
            "Real Open X files are being downloaded into data/openx_demo and monitored.",
            "Current incremental allocation-head training uses complete files only, excluding .gstmp/.tmp/.part partial downloads.",
            "The current Q-Tail allocation head is directionally aligned with the PT-heavy-tail goal.",
            "The local API can turn new embodied-task CSV data into a Q-Tail synthetic allocation package.",
            "The public customer-style service package passes the same-budget data-engine audit.",
        ],
        "cannot_claim_yet": [
            "Final Strong 20000-step training is not complete.",
            "Full robot-policy training has not been completed on the full RLDS/TFDS stack.",
            "Cannot yet claim language_table and language_table_sim are fully downloaded and verified.",
        ],
        "headline_metrics": {
            "incremental_trainable_gib": training_quality.get("gib"),
            "incremental_rows": training_quality.get("row_count"),
            "incremental_partial_rows": training_quality.get("partial_row_count"),
            "incremental_predicted_tail_share_gain_pp": incremental_effect.get("predicted_tail_share_gain_pp"),
            "public_tail_success_gain_pp": service_effect.get("tail_success_gain_pp"),
            "public_tail_success_relative_gain_pct": service_effect.get("tail_success_relative_gain_pct"),
            "public_tail_data_share_gain_pp": service_effect.get("tail_data_share_gain_pp"),
            "latest_api_tail_success_gain_pp": latest_api_effect.get("tail_success_gain_pp"),
        },
        "next_trigger": {
            "strong_training": "ready_for_strong_training=true",
            "incremental_refresh": "complete-file growth reaches min_growth_gib",
            "remaining_to_incremental_refresh_gib": refresh.get("remaining_to_next_refresh_gib"),
            "strong_ready": strong_verification.get("ready_for_strong_training"),
            "strong_training_complete": strong_pipeline.get("training_complete"),
        },
    }


def evidence_ledger(
    *,
    total_gib: float,
    incremental_report: dict,
    strong_report: dict,
    service_delivery: dict,
    strong_verification: dict,
    auto_refresh: dict,
    latest_api: dict,
) -> list[dict]:
    incremental_effect = incremental_report.get("effect_metrics", {})
    strong_effect = strong_report.get("effect_metrics", {})
    service_effect = service_delivery.get("effect_summary", {})
    latest_api_effect = latest_api.get("effect_summary", {})
    return [
        {
            "claim": "Real Open X data is being downloaded and monitored.",
            "status": "active",
            "evidence": f"{total_gib:.3f} GiB in data/openx_demo",
            "artifact": str(DATA_DIR),
            "boundary": "Strong download is still in progress until both language_table datasets pass verification.",
        },
        {
            "claim": "Strong final training is gated by data completeness.",
            "status": "ready" if strong_verification.get("ready_for_strong_training") else "waiting",
            "evidence": "ready_for_strong_training="
            + str(bool(strong_verification.get("ready_for_strong_training"))),
            "artifact": str(ROOT / "results" / "openx_strong_download" / "strong_download_verification.json"),
            "boundary": "Final 20000-step run is not allowed while partial .gstmp files or missing datasets remain.",
        },
        {
            "claim": "Current Open X trained model has learned a PT-heavy-tail allocation direction.",
            "status": incremental_report.get("status") or "missing",
            "evidence": "predicted_tail_share_gain_pp="
            + str(incremental_effect.get("predicted_tail_share_gain_pp")),
            "artifact": str(ROOT / "results" / "openx_incremental_training_snapshot" / "openx_demo_training_report.json"),
            "boundary": "This is the latest incremental snapshot, not the final Strong result.",
        },
        {
            "claim": "Public customer-style service package passes same-budget audit.",
            "status": "passed" if service_effect.get("decision", {}).get("passed") else "pending",
            "evidence": "tail_success_gain_pp="
            + str(service_effect.get("tail_success_gain_pp"))
            + "; tail_data_share_gain_pp="
            + str(service_effect.get("tail_data_share_gain_pp")),
            "artifact": str(ROOT / "results" / "qtail_openx_service_public" / "qtail_service_delivery_report.json"),
            "boundary": "Customer package validates data allocation quality before full robot-policy retraining.",
        },
        {
            "claim": "The local Q-Tail API can turn new embodied data into a PT-heavy-tail delivery package.",
            "status": "passed" if latest_api_effect.get("decision", {}).get("passed") else "available",
            "evidence": "latest_run="
            + str(latest_api.get("run_id"))
            + "; winner="
            + str(latest_api_effect.get("decision", {}).get("winner")),
            "artifact": latest_api.get("package_zip") or latest_api.get("output_dir"),
            "boundary": "API output is a synthetic allocation/scenario package; downstream renderers produce final trajectories.",
        },
        {
            "claim": "Auto-refresh keeps the service package aligned with newly downloaded shards.",
            "status": auto_refresh.get("status") or "unknown",
            "evidence": "growth_gib="
            + str(auto_refresh.get("growth_gib"))
            + "; last_refreshed_gib="
            + str(auto_refresh.get("last_refreshed_gib")),
            "artifact": str(ROOT / "results" / "qtail_auto_refresh" / "refresh_status.json"),
            "boundary": "Incremental retrain runs after the configured growth threshold is met.",
        },
        {
            "claim": "Final Strong result will automatically replace the public service package.",
            "status": strong_report.get("status") or "queued",
            "evidence": "strong_steps=" + str(strong_report.get("steps")),
            "artifact": str(ROOT / "results" / "openx_strong_training" / "openx_demo_training_report.json"),
            "boundary": "This claim becomes complete only after Strong verification and training succeed.",
        },
    ]


def objective_progress(
    *,
    total_gib: float,
    incremental_report: dict,
    strong_report: dict,
    service_delivery: dict,
    strong_verification: dict,
    strong_pipeline: dict,
    latest_api: dict,
    refresh: dict,
    training_quality: dict,
) -> list[dict]:
    incremental_effect = incremental_report.get("effect_metrics", {})
    strong_effect = strong_report.get("effect_metrics", {})
    service_effect = service_delivery.get("effect_summary", {})
    latest_api_effect = latest_api.get("effect_summary", {})
    return [
        {
            "requirement": "Download real Open X data into data/ and monitor it.",
            "status": "active",
            "evidence": f"{total_gib:.3f} GiB downloaded; strong_ready={bool(strong_verification.get('ready_for_strong_training'))}",
            "artifact": str(DATA_DIR),
            "next_step": "Finish language_table and language_table_sim, then pass strong verification.",
        },
        {
            "requirement": "Start training after the download is complete.",
            "status": "waiting_for_download"
            if not strong_pipeline.get("training_complete")
            else "complete",
            "evidence": (
                "Strong waiter is armed; final marker="
                + str(bool(strong_pipeline.get("training_complete")))
                + "; wait_policy="
                + str(strong_pipeline.get("wait_policy"))
            ),
            "artifact": str(ROOT / "results" / "openx_strong_training" / "train_after_download.log"),
            "next_step": "The launchd waiter runs 20000-step training only after require-ready verification succeeds.",
        },
        {
            "requirement": "Show what was done and every step of progress on a new page.",
            "status": "implemented",
            "evidence": "qtail-openx-training.html reads progress_manifest.json and progress_history.json.",
            "artifact": str(ROOT / "qtail-openx-training.html"),
            "next_step": "After Strong training, the same page switches to the Strong result automatically.",
        },
        {
            "requirement": "Explain effect and whether it matches the PT-heavy-tail embodied-AI goal.",
            "status": "incremental_evidence",
            "evidence": "incremental predicted_tail_share_gain_pp="
            + str(incremental_effect.get("predicted_tail_share_gain_pp"))
            + "; strong predicted_tail_share_gain_pp="
            + str(strong_effect.get("predicted_tail_share_gain_pp"))
            + "; clean_training_rows="
            + str(training_quality.get("clean")),
            "artifact": str(ROOT / "results" / "openx_incremental_training_snapshot" / "openx_demo_training_report.json"),
            "next_step": "Replace incremental evidence with Strong 20000-step evidence after download completion.",
        },
        {
            "requirement": "Implement a data service that turns new embodied data into PT-heavy-tail synthetic data.",
            "status": "implemented",
            "evidence": "latest_api_run="
            + str(latest_api.get("run_id"))
            + "; api_tail_success_gain_pp="
            + str(latest_api_effect.get("tail_success_gain_pp")),
            "artifact": latest_api.get("package_zip") or str(ROOT / "tools" / "qtail_service_api.py"),
            "next_step": "Keep API calibrated to the latest incremental or Strong Open X training report.",
        },
        {
            "requirement": "Provide a customer-facing delivery package for embodied-AI companies.",
            "status": "passed" if service_effect.get("decision", {}).get("passed") else "pending",
            "evidence": "tail_success_gain_pp="
            + str(service_effect.get("tail_success_gain_pp"))
            + "; tail_data_share_gain_pp="
            + str(service_effect.get("tail_data_share_gain_pp")),
            "artifact": service_delivery.get("package_zip")
            or str(ROOT / "results" / "qtail_openx_service_public"),
            "next_step": "Rebuild package from Strong result when final training completes.",
        },
        {
            "requirement": "Keep progress updated while the long download/training runs.",
            "status": refresh.get("reason") or "active",
            "evidence": "refresh_current_gib="
            + str(refresh.get("current_gib"))
            + "; next_refresh_at_gib="
            + str(refresh.get("next_refresh_at_gib")),
            "artifact": str(ROOT / "results" / "openx_training_progress" / "progress_manifest.json"),
            "next_step": "Auto-refresh retrains the incremental snapshot after enough new data lands.",
        },
    ]


def service_execution(
    *,
    total_gib: float,
    trainable_gib: float,
    incremental_report: dict,
    strong_pipeline: dict,
    service_delivery: dict,
    latest_api: dict,
    refresh: dict,
) -> dict:
    incremental_effect = incremental_report.get("effect_metrics") or {}
    service_effect = service_delivery.get("effect_summary") or {}
    latest_api_effect = latest_api.get("effect_summary") or {}
    return {
        "product_thesis": (
            "Train and operate a Q-Tail model that converts customer embodied-AI data profiles "
            "into PT-heavy-tail synthetic data allocation packages, so customers can spend the "
            "same training budget on more rare/high-risk tasks."
        ),
        "current_stage": "incremental_openx_trained_service_live",
        "proved_now": [
            "Real Open X shards are being downloaded and used for allocation-head training.",
            "The current incremental model shifts predicted allocation mass toward tail shards.",
            "The customer-facing service/API can generate auditable PT-heavy-tail data packages.",
            "Same-budget audit packages are produced with tail success, CVaR, and tail data share metrics.",
        ],
        "not_proved_yet": [
            "Final Strong 20000-step training is still gated on full language_table/language_table_sim download.",
            "Full robot policy training on raw trajectories is not complete in this local environment.",
            "Synthetic allocation rows still need downstream renderers/adapters to become executable robot trajectories.",
        ],
        "next_milestone": {
            "trigger": "ready_for_strong_training=true",
            "action": "run 20000-step Strong training, rebuild service package, run post-Strong customer API sample, refresh page",
            "status": "complete" if strong_pipeline.get("training_complete") else "waiting_for_strong_download",
        },
        "metrics": {
            "downloaded_total_gib": total_gib,
            "trainable_complete_gib": trainable_gib,
            "incremental_predicted_tail_share_gain_pp": incremental_effect.get("predicted_tail_share_gain_pp"),
            "public_tail_success_gain_pp": service_effect.get("tail_success_gain_pp"),
            "public_tail_success_relative_gain_pct": service_effect.get("tail_success_relative_gain_pct"),
            "public_tail_data_share_gain_pp": service_effect.get("tail_data_share_gain_pp"),
            "latest_api_tail_success_gain_pp": latest_api_effect.get("tail_success_gain_pp"),
            "latest_api_tail_data_share_gain_pp": latest_api_effect.get("tail_data_share_gain_pp"),
            "next_incremental_refresh_at_gib": refresh.get("next_refresh_at_gib"),
        },
        "business_value": [
            {
                "value": "Reduce wasted embodied-AI training budget on already-common head tasks.",
                "evidence": "Q-Tail reallocates data mass toward high tail_score tasks under the same total synthetic budget.",
                "metric": "tail_data_share_gain_pp="
                + str(service_effect.get("tail_data_share_gain_pp")),
            },
            {
                "value": "Improve robustness on rare and high-risk task buckets before customers run expensive policy training.",
                "evidence": "Service packages report tail success, CVaR@20, extreme failure, and paired-bootstrap gates.",
                "metric": "tail_success_gain_pp="
                + str(service_effect.get("tail_success_gain_pp")),
            },
            {
                "value": "Turn customer datasets into repeatable, auditable synthetic-data delivery packages.",
                "evidence": "POST /generate writes report, model card, synthetic plan, README, manifest, and zip.",
                "metric": "latest_api_run=" + str(latest_api.get("run_id")),
            },
            {
                "value": "Create a product loop that improves as more Open X shards and customer data arrive.",
                "evidence": "Auto-refresh updates incremental training and the service package after complete-file growth.",
                "metric": "next_refresh_at_gib=" + str(refresh.get("next_refresh_at_gib")),
            },
        ],
        "operating_model": [
            {
                "stage": "Customer intake",
                "input": "CSV/RLDS summary with task, count, success_rate, difficulty, and group columns",
                "output": "normalized task profiles with tail_score and source allocation",
            },
            {
                "stage": "Q-Tail inference",
                "input": "customer profiles + Open X trained tail prior",
                "output": "PT-heavy-tail synthetic allocation/spec rows under the same total budget",
            },
            {
                "stage": "Audit",
                "input": "source allocation and Q-Tail allocation",
                "output": "tail success, CVaR@20, tail data share, extreme failure, claim boundary",
            },
            {
                "stage": "Delivery",
                "input": "validated report and synthetic plan",
                "output": "customer zip package ready for renderer/trajectory adapter integration",
            },
        ],
        "upgrade_path": [
            {
                "milestone": "Now",
                "status": "live_incremental_service",
                "deliverable": "API + customer package generated from incremental Open X allocation-head snapshot",
            },
            {
                "milestone": "After Strong download",
                "status": "armed",
                "deliverable": "20000-step Strong training, rebuilt public package, post-Strong customer API samples",
            },
            {
                "milestone": "GPU policy stage",
                "status": "planned",
                "deliverable": "full RLDS/TFDS policy-training adapter and policy-level tail success validation",
            },
            {
                "milestone": "Commercial pilot",
                "status": "planned",
                "deliverable": "company-specific renderer/trajectory adapter plus recurring dataset refresh reports",
            },
        ],
        "layers": [
            {
                "layer": "1. Open X evidence substrate",
                "status": "active_downloading",
                "implemented": f"{total_gib:.3f} GiB on disk; {trainable_gib:.3f} GiB complete-file training input",
                "artifact": str(DATA_DIR),
                "next_step": "Finish language_table and language_table_sim, then verify Strong gate.",
            },
            {
                "layer": "2. Q-Tail allocation-head model",
                "status": "implemented_incremental",
                "implemented": "Trains on complete Open X TFRecord shards and predicts PT-heavy-tail allocation weights.",
                "artifact": str(ROOT / "results" / "openx_incremental_training_snapshot" / "openx_demo_training_report.json"),
                "next_step": "Replace incremental checkpoint with Strong 20000-step checkpoint after download completion.",
            },
            {
                "layer": "3. Synthetic data engine",
                "status": "implemented",
                "implemented": "Maps customer task profiles to PT-heavy-tail synthetic allocation/spec CSV plus same-budget comparison.",
                "artifact": str(ROOT / "results" / "qtail_openx_service_public" / "qtail_service_synthetic_plan.csv"),
                "next_step": "Attach renderer/trajectory adapters for customer-specific embodied-AI stacks.",
            },
            {
                "layer": "4. Customer API",
                "status": "implemented_live_local",
                "implemented": "POST /generate accepts new CSV and creates a delivery package with report, model card, README, and zip.",
                "artifact": str(ROOT / "tools" / "qtail_service_api.py"),
                "next_step": "Keep API source selection pinned to Strong report once Strong training completes.",
            },
            {
                "layer": "5. Audit and claim boundary",
                "status": "implemented",
                "implemented": "Validates same-budget gates, tail success, CVaR@20, tail data share, and explicit claim boundaries.",
                "artifact": str(ROOT / "tools" / "qtail_validate_package.py"),
                "next_step": "Add policy-training audit once raw trajectory policy runs are available.",
            },
            {
                "layer": "6. Customer delivery package",
                "status": "implemented",
                "implemented": "Produces package_manifest, qtail_delivery_package.zip, README_QTAIL_DELIVERY, synthetic plan, and reports.",
                "artifact": service_delivery.get("package_zip")
                or str(ROOT / "results" / "qtail_openx_service_public"),
                "next_step": "Version packages by customer/run and by training source: incremental vs Strong.",
            },
            {
                "layer": "7. Continuous refresh",
                "status": "implemented",
                "implemented": "Auto-refresh retrains incremental snapshots when complete-file data grows enough.",
                "artifact": str(ROOT / "results" / "qtail_auto_refresh" / "refresh_status.json"),
                "next_step": "Let the running loop trigger the next refresh at the configured growth threshold.",
            },
            {
                "layer": "8. Full robot-policy training",
                "status": "planned_not_complete",
                "implemented": "Not yet completed; current work is allocation/data-service training, not full policy learning.",
                "artifact": str(ROOT / "docs" / "experiments" / "qtail_data_engine_protocol.md"),
                "next_step": "Run full RLDS/TFDS policy training on the prepared GPU environment after Strong data is verified.",
            },
        ],
    }


def gate_decision_summary(
    *,
    trainable_gib: float,
    refresh: dict,
    strong_verification: dict,
    strong_pipeline: dict,
    partial_inventory: dict,
    auto_refresh: dict,
) -> list[dict]:
    language_sim = next(
        (
            item
            for item in strong_verification.get("datasets") or []
            if item.get("dataset") == "language_table_sim"
        ),
        {},
    )
    strong_ready = bool(strong_verification.get("ready_for_strong_training"))
    incremental_ready = bool(refresh.get("will_refresh_now"))
    return [
        {
            "gate": "Incremental retrain",
            "status": "ready" if incremental_ready else "waiting",
            "release_condition": "complete-file trainable data grows by at least min_growth_gib or min_new_shards",
            "current_evidence": (
                f"trainable_gib={trainable_gib:.3f}; "
                f"next_refresh_at_gib={refresh.get('next_refresh_at_gib')}; "
                f"growth_since_refresh_gib={refresh.get('growth_since_refresh_gib')}; "
                f"current_shards={refresh.get('current_shard_count')}; "
                f"next_refresh_at_shards={refresh.get('next_refresh_at_shard_count')}; "
                f"shard_growth={refresh.get('shard_growth_since_refresh')}"
            ),
            "next_action": "Run qtail_auto_refresh training" if incremental_ready else "Wait for complete TFRecord shards, not partial bytes.",
        },
        {
            "gate": "Strong download verification",
            "status": "ready" if strong_ready else "waiting",
            "release_condition": "language_table and language_table_sim meet size/metadata requirements and no partial files remain",
            "current_evidence": (
                f"language_table_sim_gib={language_sim.get('gib')}; "
                f"language_table_sim_partial_files={language_sim.get('partial_file_count')}; "
                f"errors={','.join(str(x) for x in strong_verification.get('errors') or [])}"
            ),
            "next_action": "Allow 20000-step Strong training" if strong_ready else "Continue resumable gsutil rsync until .gstmp files become complete TFRecords.",
        },
        {
            "gate": "Partial-byte exclusion",
            "status": "enforced",
            "release_condition": "partial files are promoted to complete files by gsutil",
            "current_evidence": (
                f"partial_files={partial_inventory.get('row_count')}; "
                f"partial_gib={partial_inventory.get('total_gib')}; "
                f"recent_active={partial_inventory.get('active_recent_count')}"
            ),
            "next_action": "Keep excluding .gstmp/.tmp/.part from training rows.",
        },
        {
            "gate": "Strong final training",
            "status": "complete" if strong_pipeline.get("training_complete") else "armed_waiting",
            "release_condition": "ready_for_strong_training=true",
            "current_evidence": (
                f"download_complete={strong_pipeline.get('download_complete')}; "
                f"training_complete={strong_pipeline.get('training_complete')}"
            ),
            "next_action": "Run 20000-step training and rebuild service package after verification passes.",
        },
        {
            "gate": "Customer service package",
            "status": "live_incremental",
            "release_condition": "latest validated training source is available",
            "current_evidence": (
                f"auto_refresh_status={auto_refresh.get('status')}; "
                f"last_refreshed_gib={auto_refresh.get('last_refreshed_gib')}"
            ),
            "next_action": "Serve current incremental model now; switch to Strong checkpoint after final training.",
        },
    ]


def post_strong_acceptance(strong_pipeline: dict) -> dict:
    metaworld_response = ROOT / "results" / "qtail_service_api_runs" / "latest_metaworld_client_response.json"
    semifinal_response = ROOT / "results" / "qtail_service_api_runs" / "latest_semifinal_customer_response.json"
    metaworld_payload = load_json(metaworld_response)
    semifinal_payload = load_json(semifinal_response)
    strong_complete = bool(strong_pipeline.get("training_complete"))
    semifinal_is_strong = semifinal_payload.get("training_source") == "strong_openx_snapshot"
    metaworld_is_strong = metaworld_payload.get("training_source") == "strong_openx_snapshot"
    return {
        "status": "complete" if strong_complete and semifinal_is_strong and metaworld_is_strong else "armed_waiting",
        "completion_condition": "Strong training complete, public package rebuilt, MetaWorld and semifinal customer API samples generated from strong_openx_snapshot, latest semifinal package validated.",
        "samples": [
            {
                "name": "MetaWorld benchmark customer",
                "input": str(ROOT / "data" / "metaworld_benchmark_anchor.csv"),
                "latest_response": str(metaworld_response),
                "exists": metaworld_response.exists(),
                "training_source": metaworld_payload.get("training_source"),
                "run_id": metaworld_payload.get("run_id"),
                "tail_success_gain_pp": (metaworld_payload.get("effect_summary") or {}).get("tail_success_gain_pp"),
                "expected_after_strong": "training_source=strong_openx_snapshot",
            },
            {
                "name": "Semifinal customer embodied tasks",
                "input": str(ROOT / "data" / "customer_semifinal_embodied_tasks.csv"),
                "latest_response": str(semifinal_response),
                "exists": semifinal_response.exists(),
                "training_source": semifinal_payload.get("training_source"),
                "run_id": semifinal_payload.get("run_id"),
                "tail_success_gain_pp": (semifinal_payload.get("effect_summary") or {}).get("tail_success_gain_pp"),
                "expected_after_strong": "training_source=strong_openx_snapshot and package validator valid=true",
            },
        ],
        "validator": {
            "command": "python3 tools/qtail_validate_package.py <post-strong-output-dir>/qtail_data_engine_report.json",
            "latest_semifinal_response": str(semifinal_response),
        },
    }


def refresh_policy(total_gib: float, auto_refresh: dict) -> dict:
    min_growth = float(auto_refresh.get("min_growth_gib") or 2.0)
    min_new_shards = int(auto_refresh.get("min_new_shards") or 1)
    last_refreshed = auto_refresh.get("last_refreshed_gib")
    if last_refreshed is None:
        last_refreshed = 0.0
    last_refreshed = float(last_refreshed)
    growth = max(total_gib - last_refreshed, 0.0)
    remaining = max(min_growth - growth, 0.0)
    current_shards = auto_refresh.get("current_shard_count")
    last_refreshed_shards = (
        auto_refresh.get("last_refreshed_shard_count")
        or auto_refresh.get("last_refreshed_shards")
    )
    try:
        current_shards_int = int(current_shards)
        last_refreshed_shards_int = int(last_refreshed_shards or 0)
        shard_growth = max(current_shards_int - last_refreshed_shards_int, 0)
        remaining_shards = max(min_new_shards - shard_growth, 0)
        next_refresh_at_shards = last_refreshed_shards_int + min_new_shards
    except Exception:
        current_shards_int = None
        last_refreshed_shards_int = None
        shard_growth = None
        remaining_shards = None
        next_refresh_at_shards = None
    will_refresh = remaining <= 0 or (shard_growth is not None and shard_growth >= min_new_shards)
    return {
        "mode": "growth_threshold",
        "min_growth_gib": min_growth,
        "min_new_shards": min_new_shards,
        "last_refreshed_gib": round(last_refreshed, 3),
        "current_gib": round(total_gib, 3),
        "growth_since_refresh_gib": round(growth, 3),
        "remaining_to_next_refresh_gib": round(remaining, 3),
        "next_refresh_at_gib": round(last_refreshed + min_growth, 3),
        "last_refreshed_shard_count": last_refreshed_shards_int,
        "current_shard_count": current_shards_int,
        "shard_growth_since_refresh": shard_growth,
        "remaining_shards_to_next_refresh": remaining_shards,
        "next_refresh_at_shard_count": next_refresh_at_shards,
        "will_refresh_now": will_refresh,
        "reason": (
            "threshold_met"
            if will_refresh
            else "waiting_for_more_downloaded_data"
        ),
    }


def launch_status() -> dict:
    text = run(["launchctl", "list"])
    labels = [
        "qtail-service-api",
        "qtail-download-watchdog",
        "qtail-auto-refresh-loop",
        "qtail-openx-demo-download",
        "qtail-openx-demo-train",
        "qtail-openx-demo-train-after-download",
        "qtail-openx-strong-addon",
        "qtail-openx-strong-train-after-download",
    ]
    status = {}
    for label in labels:
        row = next((line for line in text.splitlines() if line.endswith(label)), "")
        if not row:
            status[label] = {"state": "not_running"}
            continue
        parts = row.split()
        status[label] = {
            "state": "running" if parts and parts[0] != "-" else "loaded_or_waiting",
            "pid": None if not parts or parts[0] == "-" else parts[0],
            "raw": row,
        }
    return status


def download_health(log_path: Path, progress: dict, wait_guard: dict) -> dict:
    text = read_tail_text(log_path, max_bytes=4 * 1024 * 1024)
    ps_text = run(["ps", "aux"])
    gsutil_processes = []
    for line in ps_text.splitlines():
        if (
            "gsutil" in line
            and "gdm-robotics-open-x-embodiment" in line
            and "data/openx_demo" in line
        ):
            parts = line.split(None, 10)
            gsutil_processes.append({
                "user": parts[0] if len(parts) > 0 else None,
                "pid": parts[1] if len(parts) > 1 else None,
                "cpu_pct": parts[2] if len(parts) > 2 else None,
                "mem_pct": parts[3] if len(parts) > 3 else None,
                "started": parts[8] if len(parts) > 8 else None,
                "command": parts[10] if len(parts) > 10 else line,
            })
    retry_count = len(re.findall(r"Retrying request", text))
    connection_refused_count = len(re.findall(r"Connection refused", text))
    resumable_exception_count = len(re.findall(r"ResumableDownloadException", text))
    log_age = progress.get("log_age_seconds")
    process_alive = bool(gsutil_processes)
    log_fresh = bool(progress.get("fresh"))
    if process_alive and log_fresh and connection_refused_count == 0:
        state = "healthy"
    elif process_alive and log_fresh:
        state = "recovering_network_retries"
    elif process_alive:
        state = "process_alive_log_stale"
    else:
        state = "no_active_gsutil_process"
    return {
        "state": state,
        "process_alive": process_alive,
        "gsutil_process_count": len(gsutil_processes),
        "gsutil_processes": gsutil_processes[:8],
        "log_fresh": log_fresh,
        "log_age_seconds": log_age,
        "retry_count_tail_window": retry_count,
        "connection_refused_count_tail_window": connection_refused_count,
        "resumable_exception_count_tail_window": resumable_exception_count,
        "latest_progress_line": progress.get("line"),
        "wait_guard_ready": wait_guard.get("ready_for_strong_training"),
        "wait_guard_error_count": wait_guard.get("error_count"),
        "wait_guard_errors": wait_guard.get("errors") or [],
        "recovery_policy": "gsutil rsync is resumable; train_after_download polls require-ready and will not start while partial files or missing datasets remain.",
    }


def api_response_from_run_dir(run_dir: Path) -> dict:
    direct_response = run_dir / "api_response.json"
    if direct_response.exists():
        payload = load_json(direct_response)
        payload["api_response_path"] = str(direct_response)
        payload.setdefault("run_id", run_dir.name)
        return payload

    delivery_path = run_dir / "qtail_service_delivery_report.json"
    if not delivery_path.exists():
        return {}

    delivery = load_json(delivery_path)
    manifest = load_json(run_dir / "package_manifest.json")
    customer_package = delivery.get("customer_package") or manifest
    payload = {
        "ok": bool((customer_package.get("validation") or {}).get("valid", True)),
        "run_id": run_dir.name,
        "training_source": delivery.get("training_source"),
        "output_dir": delivery.get("output_dir") or str(run_dir),
        "delivery_report": str(delivery_path),
        "readme": delivery.get("readme") or str(run_dir / "README_QTAIL_DELIVERY.md"),
        "model_card": delivery.get("model_card") or str(run_dir / "qtail_service_model_card.json"),
        "synthetic_plan": delivery.get("synthetic_plan") or str(run_dir / "qtail_service_synthetic_plan.csv"),
        "package_zip": delivery.get("package_zip") or str(run_dir / "qtail_delivery_package.zip"),
        "package_manifest": str(run_dir / "package_manifest.json"),
        "data_engine_report": customer_package.get("report") or str(run_dir / "qtail_data_engine_report.json"),
        "effect_summary": delivery.get("effect_summary") or {},
        "api_response_path": str(delivery_path),
    }
    return payload


def api_run_candidates() -> list[dict]:
    runs_dir = ROOT / "results" / "qtail_service_api_runs"
    if not runs_dir.exists():
        return []
    rows = []
    for run_dir in runs_dir.iterdir():
        if not run_dir.is_dir():
            continue
        markers = [
            run_dir / "api_response.json",
            run_dir / "qtail_service_delivery_report.json",
            run_dir / "package_manifest.json",
        ]
        existing = [path for path in markers if path.exists()]
        if not existing:
            continue
        payload = api_response_from_run_dir(run_dir)
        if not payload:
            continue
        rows.append({
            "mtime": max(path.stat().st_mtime for path in existing),
            "path": run_dir,
            "payload": payload,
        })
    return sorted(rows, key=lambda row: row["mtime"], reverse=True)


def latest_api_response() -> dict:
    preferred_latest_files = [
        ROOT / "results" / "qtail_service_api_runs" / "latest_semifinal_customer_response.json",
        ROOT / "results" / "qtail_service_api_runs" / "latest_metaworld_client_response.json",
    ]
    for path in preferred_latest_files:
        payload = load_json(path)
        if payload.get("effect_summary"):
            payload.setdefault("api_response_path", str(path))
            return payload
    candidates = api_run_candidates()
    if not candidates:
        return {}
    for candidate in candidates:
        payload = candidate["payload"]
        if payload.get("effect_summary"):
            return payload
    return candidates[0]["payload"]


def api_run_history(limit: int = 8) -> list[dict]:
    rows = []
    for candidate in api_run_candidates()[:limit]:
        payload = candidate["payload"]
        effect = payload.get("effect_summary") or {}
        decision = effect.get("decision") or {}
        rows.append({
            "run_id": payload.get("run_id") or candidate["path"].name,
            "winner": decision.get("winner"),
            "passed": decision.get("passed"),
            "tail_success_gain_pp": effect.get("tail_success_gain_pp"),
            "tail_success_relative_gain_pct": effect.get("tail_success_relative_gain_pct"),
            "cvar20_gain_pp": effect.get("cvar20_gain_pp"),
            "tail_data_share_gain_pp": effect.get("tail_data_share_gain_pp"),
            "aligned_with_pt_tail_goal": effect.get("aligned_with_pt_tail_goal"),
            "output_dir": payload.get("output_dir"),
            "readme": payload.get("readme"),
            "synthetic_plan": payload.get("synthetic_plan"),
            "package_zip": payload.get("package_zip"),
        })
    return rows


def training_ledger(limit: int = 12) -> dict:
    path = ROOT / "results" / "qtail_auto_refresh" / "training_ledger.json"
    payload = load_json(path)
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    return {
        "path": str(path),
        "row_count": len(rows),
        "rows": rows[-limit:],
    }


def dataset_inventory() -> list[dict]:
    if not DATA_DIR.exists():
        return []
    rows = []
    for ds in sorted(p for p in DATA_DIR.iterdir() if p.is_dir()):
        files = [p for p in ds.rglob("*") if p.is_file()]
        size = sum(p.stat().st_size for p in files)
        trainable_files = [p for p in files if not is_partial_download(p)]
        trainable_size = sum(p.stat().st_size for p in trainable_files)
        tfrecords = [p for p in files if "tfrecord" in p.name]
        trainable_tfrecords = [p for p in tfrecords if not is_partial_download(p)]
        partial_files = [p for p in files if is_partial_download(p)]
        rows.append({
            "dataset": ds.name,
            "bytes": size,
            "gib": round(size / (1024**3), 3),
            "trainable_bytes": trainable_size,
            "trainable_gib": round(trainable_size / (1024**3), 3),
            "file_count": len(files),
            "tfrecord_count": len(tfrecords),
            "trainable_tfrecord_count": len(trainable_tfrecords),
            "partial_file_count": len(partial_files),
        })
    return rows


def partial_download_inventory(limit: int = 24) -> dict:
    rows = []
    if DATA_DIR.exists():
        now_ts = datetime.now(timezone.utc).timestamp()
        for path in DATA_DIR.rglob("*"):
            if not path.is_file() or not is_partial_download(path):
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            dataset = None
            try:
                rel_parts = path.relative_to(DATA_DIR).parts
                dataset = rel_parts[0] if rel_parts else None
            except ValueError:
                pass
            mtime_utc = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
            rows.append({
                "dataset": dataset,
                "path": str(path),
                "relative_path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
                "bytes": stat.st_size,
                "mib": round(stat.st_size / (1024**2), 2),
                "gib": round(stat.st_size / (1024**3), 3),
                "mtime_utc": mtime_utc.isoformat(),
                "mtime_local": mtime_utc.astimezone(LOCAL_TZ).isoformat(),
                "age_seconds": round(max(0.0, now_ts - stat.st_mtime), 1),
                "recently_active": (now_ts - stat.st_mtime) <= 15 * 60,
            })
    rows.sort(key=lambda row: row["mtime_utc"], reverse=True)
    total_bytes = sum(row["bytes"] for row in rows)
    active_rows = [row for row in rows if row["recently_active"]]
    return {
        "policy": "Partial .gstmp/.tmp/.part files are visible download evidence but excluded from training until promoted to complete TFRecord files.",
        "row_count": len(rows),
        "active_recent_count": len(active_rows),
        "total_bytes": total_bytes,
        "total_gib": round(total_bytes / (1024**3), 3),
        "latest_mtime_local": rows[0]["mtime_local"] if rows else None,
        "rows": rows[:limit],
    }


def training_rows_quality(path: Path) -> dict:
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "row_count": 0,
            "partial_row_count": None,
            "clean": False,
        }
    row_count = 0
    partial_row_count = 0
    bytes_sum = 0
    datasets = set()
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                row_count += 1
                row_path = Path(row.get("path") or "")
                if is_partial_download(row_path):
                    partial_row_count += 1
                try:
                    bytes_sum += int(float(row.get("bytes") or 0))
                except Exception:
                    pass
                if row.get("dataset"):
                    datasets.add(row["dataset"])
    except Exception as exc:
        return {
            "path": str(path),
            "exists": True,
            "row_count": row_count,
            "partial_row_count": partial_row_count,
            "clean": False,
            "error": str(exc),
        }
    return {
        "path": str(path),
        "exists": True,
        "row_count": row_count,
        "partial_row_count": partial_row_count,
        "clean": partial_row_count == 0 and row_count > 0,
        "bytes": bytes_sum,
        "gib": round(bytes_sum / (1024**3), 3),
        "dataset_count": len(datasets),
        "datasets": sorted(datasets),
        "byte_policy": "complete_files_only_excluding_gstmp_tmp_part",
    }


def progress_history_key(row: dict) -> tuple:
    return (
        row.get("data_gib"),
        row.get("download_files_done"),
        row.get("download_percent"),
        row.get("incremental_total_gib"),
        row.get("incremental_steps"),
        row.get("auto_refresh_status"),
        row.get("strong_ready"),
        row.get("strong_training_complete"),
    )


def update_progress_history(manifest: dict, limit: int = 240) -> list[dict]:
    history_path = OUT_DIR / "progress_history.json"
    current = manifest.get("download_progress") or {}
    incremental = manifest.get("training", {}).get("incremental_report") or {}
    incremental_effect = incremental.get("effect_metrics") or {}
    service_effect = manifest.get("service_delivery", {}).get("delivery_report", {}).get("effect_summary") or {}
    auto_refresh = manifest.get("auto_refresh") or {}
    strong_verification = manifest.get("strong_download_verification") or {}
    strong_pipeline = manifest.get("strong_pipeline") or {}
    row = {
        "generated_at": manifest["generated_at"],
        "generated_at_local": manifest.get("generated_at_local"),
        "data_gib": manifest.get("data", {}).get("total_gib"),
        "dataset_count": manifest.get("data", {}).get("dataset_count"),
        "download_dataset": current.get("active_dataset"),
        "download_files_done": current.get("files_done"),
        "download_files_total": current.get("files_total"),
        "download_percent": current.get("percent"),
        "download_done_gib": current.get("done_gib"),
        "download_total_gib": current.get("total_gib"),
        "download_speed": current.get("speed"),
        "download_eta": current.get("eta"),
        "incremental_total_gib": incremental.get("total_gib"),
        "incremental_steps": incremental.get("steps"),
        "incremental_shards": incremental.get("shard_count"),
        "predicted_tail_share_gain_pp": incremental_effect.get("predicted_tail_share_gain_pp"),
        "service_tail_success_gain_pp": service_effect.get("tail_success_gain_pp"),
        "service_tail_data_share_gain_pp": service_effect.get("tail_data_share_gain_pp"),
        "auto_refresh_status": auto_refresh.get("status"),
        "strong_ready": strong_verification.get("ready_for_strong_training"),
        "strong_training_complete": strong_pipeline.get("training_complete"),
    }
    history = []
    if history_path.exists():
        existing = load_json(history_path)
        if isinstance(existing.get("rows"), list):
            history = existing["rows"]
    if history and progress_history_key(history[-1]) == progress_history_key(row):
        history[-1] = row
    else:
        history.append(row)
    history = history[-limit:]
    payload = {
        "generated_at": manifest["generated_at"],
        "limit": limit,
        "row_count": len(history),
        "rows": history,
    }
    history_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return history


def fmt_value(value: object, digits: int = 2) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except Exception:
        return "n/a"


def write_status_brief(manifest: dict, path: Path) -> None:
    summary = manifest.get("submission_summary") or {}
    headline = summary.get("headline_metrics") or {}
    refresh = manifest.get("refresh_policy") or {}
    progress = manifest.get("download_progress") or {}
    strong = manifest.get("strong_download_verification") or {}
    completion = manifest.get("strong_dataset_completion") or []
    health = manifest.get("download_health") or {}
    watchdog = manifest.get("download_watchdog") or {}
    partials = manifest.get("partial_downloads") or {}
    acceleration = manifest.get("download_acceleration") or {}
    gate_decisions = manifest.get("gate_decisions") or []
    lines = [
        "# Q-Tail Open X Training Status Brief",
        "",
        f"- Generated: {manifest.get('generated_at_local')} ({manifest.get('timezone')})",
        f"- Page: http://localhost:6222/qtail-openx-training",
        f"- Status: {summary.get('status', 'n/a')}",
        "",
        "## Current Download",
        "",
        f"- Active dataset: {progress.get('active_dataset', 'n/a')}",
        f"- Progress: {progress.get('files_done', 'n/a')}/{progress.get('files_total', 'n/a')} files, {progress.get('percent', 'n/a')}%",
        f"- Disk GiB: {fmt_value(manifest.get('data', {}).get('total_gib'))}",
        f"- Trainable GiB: {fmt_value(manifest.get('data', {}).get('trainable_gib'))}",
        f"- Strong ready: {strong.get('ready_for_strong_training')}",
        f"- Download health: {health.get('state', 'n/a')} · gsutil processes: {health.get('gsutil_process_count', 'n/a')} · retries in tail window: {health.get('retry_count_tail_window', 'n/a')}",
        f"- Download acceleration: threads={acceleration.get('parallel_thread_count', 'n/a')} · sliced_threshold={acceleration.get('sliced_object_download_threshold', 'n/a')} · components={acceleration.get('sliced_object_download_max_components', 'n/a')}",
        f"- Download watchdog: {watchdog.get('action', 'n/a')} · byte growth since last check: {watchdog.get('data_growth_bytes_since_last_check', 'n/a')} · no-growth seconds: {fmt_value(watchdog.get('no_data_growth_seconds'), 0)}",
        f"- Partial download files: {partials.get('row_count', 'n/a')} files · {fmt_value(partials.get('total_gib'), 3)} GiB · recent active {partials.get('active_recent_count', 'n/a')}",
        "",
        "## Latest Incremental Training",
        "",
        f"- Trainable input: {fmt_value(headline.get('incremental_trainable_gib'))} GiB",
        f"- Rows: {headline.get('incremental_rows', 'n/a')}",
        f"- Partial rows: {headline.get('incremental_partial_rows', 'n/a')}",
        f"- Predicted tail share gain: {fmt_value(headline.get('incremental_predicted_tail_share_gain_pp'))} pp",
        f"- Next incremental refresh at: {fmt_value(refresh.get('next_refresh_at_gib'))} GiB or {refresh.get('next_refresh_at_shard_count', 'n/a')} complete shards",
        f"- Remaining to next refresh: {fmt_value(refresh.get('remaining_to_next_refresh_gib'), 3)} GiB or {refresh.get('remaining_shards_to_next_refresh', 'n/a')} complete shards",
        "",
        "## Service Package Metrics",
        "",
        f"- Public tail success gain: {fmt_value(headline.get('public_tail_success_gain_pp'))} pp",
        f"- Public tail success relative gain: {fmt_value(headline.get('public_tail_success_relative_gain_pct'))}%",
        f"- Public tail data share gain: {fmt_value(headline.get('public_tail_data_share_gain_pp'))} pp",
        f"- Latest API tail success gain: {fmt_value(headline.get('latest_api_tail_success_gain_pp'))} pp",
        "",
        "## Productized Service Execution",
        "",
        f"- Stage: {(manifest.get('service_execution') or {}).get('current_stage', 'n/a')}",
        f"- Thesis: {(manifest.get('service_execution') or {}).get('product_thesis', 'n/a')}",
        f"- Next milestone: {((manifest.get('service_execution') or {}).get('next_milestone') or {}).get('action', 'n/a')}",
        "",
        "## Strong Dataset Completion",
        "",
    ]
    for row in completion:
        lines.extend([
            f"### {row.get('dataset')}",
            "",
            f"- Valid: {row.get('valid')}",
            f"- GiB: {fmt_value(row.get('gib'))} / {fmt_value(row.get('min_gib'))} ({fmt_value(row.get('gib_completion_pct'), 1)}%)",
            f"- TFRecord: {row.get('tfrecord_count', 'n/a')} / {row.get('min_tfrecords', 'n/a')} ({fmt_value(row.get('tfrecord_completion_pct'), 1)}%)",
            f"- Remaining: {fmt_value(row.get('remaining_gib'))} GiB, {row.get('remaining_tfrecords', 'n/a')} TFRecords",
            f"- Partial files: {row.get('partial_file_count', 'n/a')}",
            "",
        ])
    lines.extend([
        "## Can Claim Now",
        "",
    ])
    lines.extend([f"- {item}" for item in summary.get("can_claim", [])])
    lines.extend([
        "",
        "## Cannot Claim Yet",
        "",
    ])
    lines.extend([f"- {item}" for item in summary.get("cannot_claim_yet", [])])
    lines.extend([
        "",
        "## Next Trigger",
        "",
        f"- Strong training: {(summary.get('next_trigger') or {}).get('strong_training')}",
        f"- Incremental refresh: {(summary.get('next_trigger') or {}).get('incremental_refresh')}",
        "",
        "## Gate Decisions",
        "",
    ])
    for gate in gate_decisions:
        lines.extend([
            f"### {gate.get('gate', 'n/a')}",
            "",
            f"- Status: {gate.get('status', 'n/a')}",
            f"- Release condition: {gate.get('release_condition', 'n/a')}",
            f"- Current evidence: {gate.get('current_evidence', 'n/a')}",
            f"- Next action: {gate.get('next_action', 'n/a')}",
            "",
        ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_download_status(manifest: dict, path: Path) -> None:
    data = manifest.get("data") or {}
    disk = manifest.get("disk") or {}
    progress = manifest.get("download_progress") or {}
    health = manifest.get("download_health") or {}
    partials = manifest.get("partial_downloads") or {}
    completion = manifest.get("strong_dataset_completion") or []
    summary = manifest.get("submission_summary") or {}
    headline = summary.get("headline_metrics") or {}
    refresh = manifest.get("refresh_policy") or {}
    jobs = manifest.get("jobs") or {}
    strong = manifest.get("strong_download_verification") or {}
    acceleration = manifest.get("download_acceleration") or {}
    gate_decisions = manifest.get("gate_decisions") or []

    completed = []
    for row in data.get("datasets") or []:
        if row.get("partial_file_count") == 0:
            completed.append(row.get("dataset"))

    lines = [
        "# Open X Strong Evidence Download Status",
        "",
        f"Generated from the local progress manifest on {manifest.get('generated_at_local')} ({manifest.get('timezone')}).",
        "",
        "## Current State",
        "",
        f"- Download root: `{data.get('path', DATA_DIR)}`",
        "- Live page: `http://localhost:6222/qtail-openx-training`",
        f"- Live log: `{ROOT / 'results' / 'openx_strong_download' / 'download.log'}`",
        f"- Total directory size: about `{fmt_value(data.get('total_gib'))} GiB`",
        f"- Trainable complete-file size: about `{fmt_value(data.get('trainable_gib'))} GiB`",
        f"- Free disk space: about `{fmt_value(disk.get('free_gib'))} GiB`",
        f"- Disk safety for the {fmt_value(disk.get('target_strong_gib'))} GiB Strong package: `{disk.get('safety', 'n/a')}`",
        "",
        "## What Is Running",
        "",
    ]
    for label, title in [
        ("qtail-openx-strong-addon", "Downloader"),
        ("qtail-download-watchdog", "Download watchdog"),
        ("qtail-auto-refresh-loop", "Incremental auto-refresh"),
        ("qtail-openx-strong-train-after-download", "Training-after-download guard"),
        ("qtail-service-api", "Service API"),
        ("qtail-openx-progress-loop", "Page progress loop"),
    ]:
        state = (jobs.get(label) or {}).get("state", "n/a")
        lines.append(f"- {title}: `{label}` ({state})")
    lines.extend([
        "",
        (
            f"The active downloader is `gsutil rsync` on `{progress.get('active_dataset', 'n/a')}`. "
            f"The process alive flag is `{health.get('process_alive')}` and log fresh is `{health.get('log_fresh')}`."
        ),
        (
            f"The latest observed progress line was about `{progress.get('files_done', 'n/a')} / "
            f"{progress.get('files_total', 'n/a')}` files and `{fmt_value(progress.get('done_gib'))} / "
            f"{fmt_value(progress.get('total_gib'))} GiB` in the active rsync progress view. "
            f"Speed is volatile and was last observed around `{progress.get('speed', 'n/a')}`."
        ),
        (
            f"Download acceleration config: processes=`{acceleration.get('parallel_process_count', 'n/a')}`, "
            f"threads=`{acceleration.get('parallel_thread_count', 'n/a')}`, "
            f"sliced threshold=`{acceleration.get('sliced_object_download_threshold', 'n/a')}`, "
            f"components=`{acceleration.get('sliced_object_download_max_components', 'n/a')}`."
        ),
        "",
        "Partial download detail appears on the live page:",
        "",
        f"- Partial files: `{partials.get('row_count', 'n/a')}`",
        f"- Partial bytes: about `{fmt_value(partials.get('total_gib'), 3)} GiB`",
        f"- Recently active partial files: `{partials.get('active_recent_count', 'n/a')}`",
        f"- Latest partial update: `{partials.get('latest_mtime_local', 'n/a')}`",
        "",
        "## Completed Locally",
        "",
    ])
    if completed:
        lines.extend([f"- `{item}`" for item in completed])
    else:
        lines.append("- No complete datasets detected yet.")
    lines.extend([
        "",
        "## Strong Gate",
        "",
        "Strong final training has not started yet because the verification gate is not ready."
        if not strong.get("ready_for_strong_training")
        else "Strong final training is allowed because the verification gate is ready.",
        "",
    ])
    for row in completion:
        errors = ", ".join(row.get("errors") or []) or "none"
        lines.extend([
            f"- `{row.get('dataset')}`: valid=`{row.get('valid')}`, "
            f"{fmt_value(row.get('gib'))}/{fmt_value(row.get('min_gib'))} GiB, "
            f"TFRecord `{row.get('tfrecord_count', 'n/a')}/{row.get('min_tfrecords', 'n/a')}`, "
            f"partial files `{row.get('partial_file_count', 'n/a')}`, errors `{errors}`",
        ])
    lines.extend([
        "",
        f"- Current gate errors: `{', '.join(str(x) for x in strong.get('errors') or []) or 'none'}`",
        "",
        "Partial `.gstmp` files are excluded from training until `gsutil` finishes and promotes them into complete TFRecord files. This avoids training on truncated shards.",
        "",
        "## Training State",
        "",
        f"- Latest incremental Open X snapshot used `{fmt_value(headline.get('incremental_trainable_gib'))} GiB` of complete files across `{headline.get('incremental_rows', 'n/a')}` shard rows.",
        "- Latest incremental run used `2500` steps.",
        f"- Latest incremental effect: predicted Q-Tail tail data share gain `+{fmt_value(headline.get('incremental_predicted_tail_share_gain_pp'))} pp`.",
        "- The incremental result is consistent with the PT-heavy-tail goal.",
        f"- Next incremental refresh threshold: about `{fmt_value(refresh.get('next_refresh_at_gib'))} GiB` complete-file trainable data.",
        f"- Complete-file growth since the last refresh: `{fmt_value(refresh.get('growth_since_refresh_gib'), 3)} GiB`.",
        "- The total directory may grow before training refreshes because `.gstmp` transfer bytes are not counted as trainable data.",
        "",
        "Latest customer-style service run:",
        "",
        f"- Tail success gain: `+{fmt_value(headline.get('latest_api_tail_success_gain_pp'))} pp`",
        f"- Public tail success gain: `+{fmt_value(headline.get('public_tail_success_gain_pp'))} pp`",
        f"- Public tail success relative gain: `+{fmt_value(headline.get('public_tail_success_relative_gain_pct'))}%`",
        f"- Public tail data share gain: `+{fmt_value(headline.get('public_tail_data_share_gain_pp'))} pp`",
        "- Decision: Q-Tail synthetic wins under the same-budget evaluation protocol when the package validator passes.",
        "",
        "## Gate Decisions",
        "",
    ])
    for gate in gate_decisions:
        lines.extend([
            f"### {gate.get('gate', 'n/a')}",
            "",
            f"- Status: `{gate.get('status', 'n/a')}`",
            f"- Release condition: {gate.get('release_condition', 'n/a')}",
            f"- Current evidence: {gate.get('current_evidence', 'n/a')}",
            f"- Next action: {gate.get('next_action', 'n/a')}",
            "",
        ])
    lines.extend([
        "## Automatic Triggers",
        "",
        f"- Incremental refresh runs when complete-file trainable data grows by at least `{fmt_value(refresh.get('min_growth_gib'))} GiB` or `{refresh.get('min_new_shards', 'n/a')}` complete shard from the last trained snapshot.",
        "- Strong final training runs automatically after `language_table` and `language_table_sim` both pass verification.",
        "- The Strong final training command is guarded by `scripts/train_openx_strong_after_download.sh`; it will not start while partial files are present.",
        "- After Strong final training finishes, the public service package and progress page are refreshed from the Strong checkpoint.",
        "",
        "## Recovery Policy",
        "",
        "The watchdog restarts the Strong downloader only when the log is stale, no `gsutil` process is alive, the launchd label is absent, or downloaded bytes stop growing for the stale window.",
        "",
        f"Current correct action: {health.get('recovery_policy', 'keep monitoring the resumable download.')}",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    demo_report = load_json(ROOT / "results" / "openx_demo_training" / "openx_demo_training_report.json")
    full_demo_report = load_json(ROOT / "results" / "openx_demo_training_full_demo" / "openx_demo_training_report.json")
    incremental_report = load_json(ROOT / "results" / "openx_incremental_training_snapshot" / "openx_demo_training_report.json")
    strong_report = load_json(ROOT / "results" / "openx_strong_training" / "openx_demo_training_report.json")
    service_delivery = load_json(ROOT / "results" / "qtail_openx_service_public" / "qtail_service_delivery_report.json")
    service_model_card = load_json(ROOT / "results" / "qtail_openx_service_public" / "qtail_service_model_card.json")
    auto_refresh = load_json(ROOT / "results" / "qtail_auto_refresh" / "refresh_status.json")
    auto_refresh_loop = load_json(ROOT / "results" / "qtail_auto_refresh" / "loop_status.json")
    download_watchdog = load_json(ROOT / "results" / "openx_strong_download" / "download_watchdog_status.json")
    download_watchdog_loop = load_json(ROOT / "results" / "openx_strong_download" / "download_watchdog_loop_status.json")
    download_watchdog_history = load_json(ROOT / "results" / "openx_strong_download" / "download_watchdog_history.json")
    strong_verification = load_json(ROOT / "results" / "openx_strong_download" / "strong_download_verification.json")
    latest_cli_response = load_json(ROOT / "results" / "qtail_service_api_runs" / "latest_metaworld_client_response.json")
    latest_api = latest_api_response()
    inventory = dataset_inventory()
    partial_inventory = partial_download_inventory()
    total_bytes = sum(row["bytes"] for row in inventory)
    trainable_bytes = sum(row["trainable_bytes"] for row in inventory)
    total_gib = round(total_bytes / (1024**3), 3)
    trainable_gib = round(trainable_bytes / (1024**3), 3)
    strong_download_log = ROOT / "results" / "openx_strong_download" / "download.log"
    strong_download_marker = ROOT / "results" / "openx_strong_download" / "STRONG_DOWNLOAD_COMPLETE"
    strong_training_marker = ROOT / "results" / "openx_strong_training" / "STRONG_TRAINING_COMPLETE"
    strong_wait_status = load_json(ROOT / "results" / "openx_strong_training" / "wait_guard_status.json")
    incremental_rows_path = ROOT / "results" / "openx_incremental_training_snapshot" / "openx_shard_training_rows.csv"
    strong_rows_path = ROOT / "results" / "openx_strong_training" / "openx_shard_training_rows.csv"
    if strong_report:
        current_training_report = strong_report
        current_training_source = "strong_openx_training"
    elif incremental_report:
        current_training_report = incremental_report
        current_training_source = "incremental_openx_snapshot"
    elif full_demo_report:
        current_training_report = full_demo_report
        current_training_source = "full_demo_openx_training"
    else:
        current_training_report = demo_report
        current_training_source = "demo_openx_training"
    incremental_quality = training_rows_quality(incremental_rows_path)
    strong_quality = training_rows_quality(strong_rows_path)
    strong_pipeline = {
        "wait_policy": "poll_strong_download_verification_until_ready",
        "ready_field": "ready_for_strong_training",
        "guard_command": "python3 tools/qtail_verify_openx_strong_download.py --require-ready",
        "download_complete": strong_download_marker.exists(),
        "download_completed_at": read_text_file(strong_download_marker),
        "training_complete": strong_training_marker.exists(),
        "training_completed_at": read_text_file(strong_training_marker),
        "post_training_actions": [
            "run 20000-step Open X Strong allocation-head training",
            "rebuild qtail_openx_service_public from strong training report",
            "validate qtail_data_engine_report.json",
            "write STRONG_TRAINING_COMPLETE marker",
            "run a post-strong MetaWorld customer API sample",
            "run a post-strong semifinal customer API sample",
            "validate the latest post-strong customer package",
            "refresh progress_manifest.json for the page after the completion marker exists",
        ],
    }
    refresh = refresh_policy(trainable_gib, auto_refresh)
    download_progress = latest_gsutil_progress(strong_download_log)
    download_acceleration = latest_gsutil_config(strong_download_log)
    forecast = gate_forecast(
        total_gib=total_gib,
        trainable_gib=trainable_gib,
        download_progress=download_progress,
        refresh=refresh,
        strong_verification=strong_verification,
    )
    health = download_health(strong_download_log, download_progress, strong_wait_status)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_at_local": local_iso(),
        "timezone": "Asia/Shanghai",
        "title": "Q-Tail Open X Training Progress",
        "current_stage": "strong_download_queued_or_running",
        "data": {
            "path": str(DATA_DIR),
            "total_bytes": total_bytes,
            "total_gib": total_gib,
            "trainable_bytes": trainable_bytes,
            "trainable_gib": trainable_gib,
            "dataset_count": len(inventory),
            "datasets": inventory,
            "target_demo_gib": TARGET_DEMO_GIB,
            "target_strong_gib": TARGET_STRONG_GIB,
        },
        "disk": disk_status(total_bytes),
        "download_progress": download_progress,
        "download_acceleration": download_acceleration,
        "download_health": health,
        "partial_downloads": partial_inventory,
        "gate_forecast": forecast,
        "gate_decisions": gate_decision_summary(
            trainable_gib=trainable_gib,
            refresh=refresh,
            strong_verification=strong_verification,
            strong_pipeline=strong_pipeline,
            partial_inventory=partial_inventory,
            auto_refresh=auto_refresh,
        ),
        "strong_download_verification": strong_verification,
        "strong_dataset_completion": strong_dataset_completion(strong_verification),
        "strong_pipeline": strong_pipeline,
        "post_strong_acceptance": post_strong_acceptance(strong_pipeline),
        "strong_wait_guard": strong_wait_status,
        "jobs": launch_status(),
        "training": {
            "quick_report": current_training_report,
            "current_report_source": current_training_source,
            "full_demo_report": full_demo_report,
            "incremental_report": incremental_report,
            "incremental_rows_quality": incremental_quality,
            "strong_report": strong_report,
            "strong_rows_quality": strong_quality,
            "ledger": training_ledger(),
        },
        "service_delivery": {
            "delivery_report": service_delivery,
            "model_card": service_model_card,
            "artifacts": {
                "model_card": str(ROOT / "results" / "qtail_openx_service_public" / "qtail_service_model_card.json"),
                "delivery_report": str(ROOT / "results" / "qtail_openx_service_public" / "qtail_service_delivery_report.json"),
                "readme": service_delivery.get("readme")
                or str(ROOT / "results" / "qtail_openx_service_public" / "README_QTAIL_DELIVERY.md"),
                "synthetic_plan": str(ROOT / "results" / "qtail_openx_service_public" / "qtail_service_synthetic_plan.csv"),
                "package_manifest": str(ROOT / "results" / "qtail_openx_service_public" / "package_manifest.json"),
                "package_zip": service_delivery.get("package_zip"),
            },
        },
        "service_execution": service_execution(
            total_gib=total_gib,
            trainable_gib=trainable_gib,
            incremental_report=incremental_report,
            strong_pipeline=strong_pipeline,
            service_delivery=service_delivery,
            latest_api=latest_api,
            refresh=refresh,
        ),
        "service_api": {
            "base_url": "http://127.0.0.1:8223",
            "health_endpoint": "http://127.0.0.1:8223/health",
            "generate_endpoint": "http://127.0.0.1:8223/generate",
            "runs_endpoint": "http://127.0.0.1:8223/runs",
            "latest_response": latest_api,
            "run_history": api_run_history(),
            "cli": {
                "script": str(ROOT / "tools" / "qtail_service_client.py"),
                "example": "python3 tools/qtail_service_client.py --input data/metaworld_benchmark_anchor.csv --out results/qtail_service_api_runs/latest_metaworld_client_response.json",
                "latest_response": latest_cli_response,
            },
            "example_request": {
                "filename": "customer.csv",
                "csv_text": "task,count,success_rate,difficulty,group\\nrare_pick,12,0.32,0.91,tail\\nstandard_pick,540,0.86,0.22,head\\n",
                "synthetic_budget": 100000,
                "top_k": 128,
            },
        },
        "auto_refresh": auto_refresh,
        "auto_refresh_loop": auto_refresh_loop,
        "download_watchdog": download_watchdog,
        "download_watchdog_loop": download_watchdog_loop,
        "download_watchdog_history": {
            "path": str(ROOT / "results" / "openx_strong_download" / "download_watchdog_history.json"),
            "row_count": len(download_watchdog_history.get("rows") or []),
            "rows": (download_watchdog_history.get("rows") or [])[-24:],
        },
        "refresh_policy": refresh,
        "submission_summary": submission_summary(
            incremental_report=incremental_report,
            service_delivery=service_delivery,
            strong_verification=strong_verification,
            strong_pipeline=strong_pipeline,
            training_quality=incremental_quality,
            refresh=refresh,
            latest_api=latest_api,
        ),
        "evidence_ledger": evidence_ledger(
            total_gib=total_gib,
            incremental_report=incremental_report,
            strong_report=strong_report,
            service_delivery=service_delivery,
            strong_verification=strong_verification,
            auto_refresh=auto_refresh,
            latest_api=latest_api,
        ),
        "objective_progress": objective_progress(
            total_gib=total_gib,
            incremental_report=incremental_report,
            strong_report=strong_report,
            service_delivery=service_delivery,
            strong_verification=strong_verification,
            strong_pipeline=strong_pipeline,
            latest_api=latest_api,
            refresh=refresh,
            training_quality=incremental_quality,
        ),
        "logs": {
            "demo_download_tail": log_tail(ROOT / "results" / "openx_demo_download" / "download.log", 40),
            "strong_download_tail": log_tail(strong_download_log, 40),
            "strong_train_tail": log_tail(ROOT / "results" / "openx_strong_training" / "train_after_download.log", 40),
            "auto_refresh_tail": log_tail(ROOT / "results" / "qtail_auto_refresh" / "loop.log", 40),
        },
        "interpretation": {
            "what_we_did": [
                "Downloaded official Open X / RT-X RLDS-format subsets into data/openx_demo.",
                "Started same-architecture source-vs-Q-Tail allocation-head training on real downloaded shards.",
                "Queued Strong Evidence add-on datasets language_table and language_table_sim after the demo package.",
            ],
            "claim_boundary": [
                "Current completed training is shard-level allocation-head training on real Open X files.",
                "It is not yet full robot-policy training because TensorFlow/TFDS/RLDS policy stack is not installed in this local Python environment.",
                "The result is still directly useful for the product goal: learning a model that maps customer embodied data profiles to PT-heavy-tail synthetic allocation targets.",
            ],
            "product_goal": "Train a Q-Tail data service model that ingests new embodied-AI data, estimates task rarity/risk, generates PT-heavy-tail synthetic data/allocation specs, and gives embodied-AI companies a faster path to improve tail-task training.",
        },
        "service_design": [
            {"step": "1. Ingest", "output": "customer CSV/RLDS/trajectory summary -> task and shard profiles"},
            {"step": "2. Score", "output": "rarity, difficulty, risk, tail_score, data mass"},
            {"step": "3. Generate", "output": "PT-heavy-tail allocation and scenario/spec CSV"},
            {"step": "4. Train", "output": "allocation head / policy adapter under same budget"},
            {"step": "5. Audit", "output": "tail share, tail success proxy, CVaR, extreme failure, claim boundary"},
            {"step": "6. Deliver", "output": "customer data package and API-ready synthetic-data plan"},
        ],
    }
    history = update_progress_history(manifest)
    manifest["progress_history"] = {
        "path": str(OUT_DIR / "progress_history.json"),
        "row_count": len(history),
        "rows": history[-24:],
    }
    brief_path = OUT_DIR / "STATUS_BRIEF.md"
    download_status_path = ROOT / "results" / "openx_strong_download" / "DOWNLOAD_STATUS.md"
    manifest["status_brief"] = {
        "path": str(brief_path),
        "format": "markdown",
    }
    manifest["download_status"] = {
        "path": str(download_status_path),
        "format": "markdown",
    }
    path = OUT_DIR / "progress_manifest.json"
    write_status_brief(manifest, brief_path)
    write_download_status(manifest, download_status_path)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
