#!/usr/bin/env python3
"""Validate a buyer-produced Gate 1 delivery without claiming buyer acceptance."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlparse
import uuid


HEX64 = re.compile(r"^[0-9a-f]{64}$")
PLACEHOLDER = re.compile(r"<[^>]+>|^unverified(?:_|$)", re.IGNORECASE)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(value: object, field: str, errors: list[str]) -> str:
    text = str(value or "").strip()
    if not text or PLACEHOLDER.search(text):
        errors.append(f"{field} is missing or still contains a placeholder")
    return text


def _hash(value: object, field: str, errors: list[str]) -> str:
    text = str(value or "").strip().lower()
    if not HEX64.fullmatch(text):
        errors.append(f"{field} must be a lowercase 64-character SHA-256")
    return text


def _positive_integer(value: object, field: str, errors: list[str]) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        errors.append(f"{field} must be a positive integer")
        return 0
    if isinstance(value, bool) or number <= 0:
        errors.append(f"{field} must be a positive integer")
    return number


def _positive_number(value: object, field: str, errors: list[str]) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        errors.append(f"{field} must be a positive number")
        return 0.0
    if isinstance(value, bool) or number <= 0 or number > 1000:
        errors.append(f"{field} must be greater than 0 and no more than 1000")
    return number


def _iso8601(value: object, field: str, errors: list[str]) -> str:
    text = _text(value, field, errors)
    if not text:
        return text
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone required")
    except ValueError:
        errors.append(f"{field} must be an ISO-8601 timestamp with timezone")
    return text


def _https_url(value: object, field: str, errors: list[str]) -> str:
    text = _text(value, field, errors)
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.hostname:
        errors.append(f"{field} must be a buyer-controlled HTTPS URL")
    return text


def validate_delivery(manifest_path: Path, dataset_package: Path, production_log: Path) -> dict:
    errors: list[str] = []
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
        if not isinstance(manifest, dict):
            raise ValueError("manifest root must be an object")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return {
            "report_type": "qtail_gate1_production_backend_validation",
            "report_version": "1.0.0",
            "status": "failed",
            "contract_eligible": False,
            "buyer_signoff_required": True,
            "errors": [f"manifest is unreadable or invalid: {exc}"],
        }

    for path, label in ((dataset_package, "dataset package"), (production_log, "production log")):
        if not path.is_file():
            errors.append(f"{label} is missing or is not a regular file")
    if dataset_package.resolve() in {manifest_path.resolve(), production_log.resolve()}:
        errors.append("dataset package, manifest, and production log must be distinct files")

    if manifest.get("manifest_version") != "1.1.0":
        errors.append("manifest_version must be 1.1.0")
    if manifest.get("status") != "buyer_external_completed":
        errors.append("status must be buyer_external_completed")
    _text(manifest.get("buyer_legal_name"), "buyer_legal_name", errors)

    backend = manifest.get("production_backend") or {}
    if not isinstance(backend, dict):
        errors.append("production_backend must be an object")
        backend = {}
    for field in ("name", "version", "execution_environment", "run_id"):
        _text(backend.get(field), f"production_backend.{field}", errors)

    robot = manifest.get("robot") or {}
    if not isinstance(robot, dict):
        errors.append("robot must be an object")
        robot = {}
    for field in ("manufacturer", "model", "configuration", "action_space"):
        _text(robot.get(field), f"robot.{field}", errors)
    _positive_number(robot.get("control_frequency_hz"), "robot.control_frequency_hz", errors)
    sensors = robot.get("sensors")
    if not isinstance(sensors, list) or not sensors or any(not str(item).strip() for item in sensors):
        errors.append("robot.sensors must contain at least one named sensor")
    _hash(robot.get("calibration_sha256"), "robot.calibration_sha256", errors)

    dataset = manifest.get("dataset") or {}
    if not isinstance(dataset, dict):
        errors.append("dataset must be an object")
        dataset = {}
    dataset_format = _text(dataset.get("format"), "dataset.format", errors).lower()
    if dataset_format and "rlds" not in dataset_format and "lerobot" not in dataset_format:
        errors.append("dataset.format must identify RLDS or LeRobot")
    trajectory_count = _positive_integer(dataset.get("trajectory_count"), "dataset.trajectory_count", errors)
    frame_count = _positive_integer(dataset.get("frame_count"), "dataset.frame_count", errors)
    if trajectory_count and frame_count and frame_count < trajectory_count:
        errors.append("dataset.frame_count cannot be less than trajectory_count")
    tasks = dataset.get("task_ids")
    if not isinstance(tasks, list) or not tasks or any(not str(item).strip() for item in tasks):
        errors.append("dataset.task_ids must contain at least one task")
    _text(dataset.get("schema_version"), "dataset.schema_version", errors)
    if dataset.get("schema_validation_passed") is not True:
        errors.append("dataset.schema_validation_passed must be true")
    if dataset.get("sample_playback_passed") is not True:
        errors.append("dataset.sample_playback_passed must be true")
    declared_package_sha = _hash(dataset.get("package_sha256"), "dataset.package_sha256", errors)

    source_job_id = _text(manifest.get("source_qtail_job_id"), "source_qtail_job_id", errors)
    if source_job_id:
        try:
            uuid.UUID(source_job_id)
        except ValueError:
            errors.append("source_qtail_job_id must be a UUID")
    _hash(manifest.get("source_qtail_delivery_sha256"), "source_qtail_delivery_sha256", errors)
    _https_url(manifest.get("production_log_url"), "production_log_url", errors)
    declared_log_sha = _hash(manifest.get("production_log_sha256"), "production_log_sha256", errors)
    _iso8601(manifest.get("observed_at"), "observed_at", errors)
    boundary = _text(manifest.get("claim_boundary"), "claim_boundary", errors).lower()
    if boundary and ("buyer" not in boundary or "sign" not in boundary):
        errors.append("claim_boundary must state that external buyer signoff is still required")

    actual_package_sha = sha256_file(dataset_package) if dataset_package.is_file() else None
    actual_log_sha = sha256_file(production_log) if production_log.is_file() else None
    if actual_package_sha and declared_package_sha != actual_package_sha:
        errors.append("dataset.package_sha256 does not match the supplied dataset package")
    if actual_log_sha and declared_log_sha != actual_log_sha:
        errors.append("production_log_sha256 does not match the supplied production log")

    report = {
        "report_type": "qtail_gate1_production_backend_validation",
        "report_version": "1.0.0",
        "status": "passed" if not errors else "failed",
        "contract_eligible": False,
        "buyer_signoff_required": True,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "dataset_package_sha256": actual_package_sha,
        "production_log_sha256": actual_log_sha,
        "source_qtail_job_id": source_job_id,
        "trajectory_count": trajectory_count,
        "task_count": len(tasks) if isinstance(tasks, list) else 0,
        "errors": sorted(set(errors)),
        "claim_boundary": "Technical Gate 1 package validation only. Buyer acceptance and externally signed evidence remain required before procurement eligibility.",
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a buyer-selected production-backend Gate 1 delivery.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--dataset-package", required=True, type=Path)
    parser.add_argument("--production-log", required=True, type=Path)
    parser.add_argument("--report", type=Path, help="Optional path for the JSON validation report.")
    args = parser.parse_args()
    report = validate_delivery(args.manifest, args.dataset_package, args.production_log)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
