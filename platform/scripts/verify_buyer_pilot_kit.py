#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path, PurePosixPath
import re
import tempfile
import zipfile


PLATFORM_DIR = Path(__file__).resolve().parents[1]
KIT_DIR = PLATFORM_DIR / "public" / "buyer-kit"
MANIFEST_PATH = KIT_DIR / "manifest.json"
ARCHIVE_PATH = KIT_DIR / "qtail-buyer-pilot-kit-v1.2.0.zip"
SIDECAR_PATH = KIT_DIR / "qtail-buyer-pilot-kit-v1.2.0.zip.sha256"
ARCHIVE_ROOT = "qtail-buyer-pilot-kit-v1.2.0"
HEX64 = re.compile(r"^[0-9a-f]{64}$")

CSV_HEADERS = {
    "templates/gate2-evaluation-ledger.csv": ["protocol_version", "task_id", "seed", "condition", "allocation_method", "policy_id", "trajectory_budget", "episode_id", "success", "termination_reason", "evaluator", "observed_at_utc", "source_run_id"],
    "templates/gate3-real-robot-trials.csv": ["protocol_version", "robot_serial", "task_id", "trial_id", "condition", "controller_version", "success", "safety_incident", "emergency_stop", "cycle_time_s", "evaluator", "observed_at_utc", "video_uri", "run_log_sha256"],
    "templates/gate3-commercial-cost-ledger.csv": ["cost_period", "currency", "task_id", "cost_category", "baseline_quantity", "baseline_unit_cost", "qtail_quantity", "qtail_unit_cost", "invoice_reference", "invoice_or_ledger_sha256", "buyer_finance_owner"],
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    require(MANIFEST_PATH.is_file() and ARCHIVE_PATH.is_file() and SIDECAR_PATH.is_file(), "buyer kit generated artifacts are missing")
    manifest_bytes = MANIFEST_PATH.read_bytes()
    manifest = json.loads(manifest_bytes)
    require(manifest.get("package") == "qtail_buyer_procurement_pilot_kit", "buyer kit package id mismatch")
    require(manifest.get("version") == "1.2.0", "buyer kit version mismatch")
    require(manifest.get("template_count") == 11, "buyer kit template count mismatch")
    require(manifest.get("tool_count") == 1, "buyer kit tool count mismatch")
    require(manifest.get("contract_eligibility") is False, "blank buyer kit must never be contract eligible")
    require("no buyer data" in manifest.get("claim_boundary", ""), "buyer kit claim boundary is missing")

    records = manifest.get("files") or []
    require(len(records) == 12, "buyer kit must contain exactly 11 templates and one validator")
    record_paths = [record.get("path") for record in records]
    require(len(record_paths) == len(set(record_paths)), "buyer kit manifest has duplicate paths")
    payloads = {"manifest.json": manifest_bytes}
    for record in records:
        relative = PurePosixPath(record["path"])
        require(not relative.is_absolute() and ".." not in relative.parts, "buyer kit manifest path traversal")
        path = KIT_DIR.joinpath(*relative.parts)
        data = path.read_bytes()
        require(len(data) == record["bytes"], f"buyer kit byte mismatch: {relative}")
        require(sha256(data) == record["sha256"], f"buyer kit hash mismatch: {relative}")
        payloads[str(relative)] = data

    for gate in (1, 2, 3):
        template = json.loads(payloads[f"templates/gate{gate}-evidence.json"])
        require(template.get("evidence_scope") == "buyer_external", f"Gate {gate} scope template mismatch")
        require(not HEX64.fullmatch(str(template.get("evidence_artifact_sha256") or "")), f"Gate {gate} template contains a usable artifact hash")
        require(not HEX64.fullmatch(str(template.get("buyer_signoff_sha256") or "")), f"Gate {gate} template contains a usable signoff hash")
    require(json.loads(payloads["templates/gate1-evidence.json"])["schema_validation_passed"] is False, "Gate 1 template must default to failure")
    require(json.loads(payloads["templates/gate2-evidence.json"])["same_policy"] is False, "Gate 2 template must default to failure")
    require(json.loads(payloads["templates/gate3-evidence.json"])["safety_review_passed"] is False, "Gate 3 template must default to failure")
    contract_checklist = payloads["templates/contract-execution-checklist.md"].decode("utf-8")
    require("服务方独立签署凭证" in contract_checklist, "contract checklist is missing the provider signature proof hash")
    require("买方独立签署凭证" in contract_checklist, "contract checklist is missing the buyer signature proof hash")

    for relative, expected in CSV_HEADERS.items():
        rows = list(csv.reader(io.StringIO(payloads[relative].decode("utf-8"))))
        require(rows == [expected], f"buyer kit CSV must be a header-only blank template: {relative}")

    validator_path = KIT_DIR / "tools" / "validate_gate1_delivery.py"
    spec = importlib.util.spec_from_file_location("qtail_gate1_validator", validator_path)
    require(spec is not None and spec.loader is not None, "Gate 1 validator could not be imported")
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        dataset = root / "buyer-dataset.tar.gz"
        production_log = root / "production.log"
        dataset.write_bytes(b"buyer-production-backend-dataset-fixture")
        production_log.write_bytes(b"buyer-production-backend-log-fixture")
        blank_manifest = KIT_DIR / "templates" / "gate1-dataset-manifest.json"
        blank_report = validator.validate_delivery(blank_manifest, dataset, production_log)
        require(blank_report["status"] == "failed", "blank Gate 1 template must fail the executable validator")
        completed = json.loads(blank_manifest.read_text(encoding="utf-8"))
        completed.update({
            "status": "buyer_external_completed",
            "buyer_legal_name": "Independent Buyer Robotics Ltd.",
            "production_backend": {
                "name": "Buyer Production Backend",
                "version": "2026.07",
                "execution_environment": "buyer-controlled isolated runner",
                "run_id": "buyer-run-0001",
            },
            "robot": {
                "manufacturer": "Buyer Robotics",
                "model": "BR-1",
                "configuration": "7-DoF arm",
                "control_frequency_hz": 20,
                "action_space": "joint position",
                "sensors": ["RGB-D", "joint state"],
                "calibration_sha256": "a" * 64,
            },
            "dataset": {
                "format": "LeRobot v3",
                "trajectory_count": 2,
                "frame_count": 10,
                "task_ids": ["buyer_task_1"],
                "schema_version": "3.0",
                "schema_validation_passed": True,
                "sample_playback_passed": True,
                "package_sha256": sha256(dataset.read_bytes()),
            },
            "source_qtail_job_id": "11111111-1111-4111-8111-111111111111",
            "source_qtail_delivery_sha256": "b" * 64,
            "production_log_url": "https://buyer.example/evidence/production.log",
            "production_log_sha256": sha256(production_log.read_bytes()),
            "observed_at": "2026-07-17T00:00:00Z",
            "claim_boundary": "Technical validation only; buyer acceptance and external signature are still required.",
        })
        completed_manifest = root / "gate1-dataset-manifest.json"
        completed_manifest.write_text(json.dumps(completed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        passed_report = validator.validate_delivery(completed_manifest, dataset, production_log)
        require(passed_report["status"] == "passed", f"completed Gate 1 fixture failed validator: {passed_report['errors']}")
        require(passed_report["contract_eligible"] is False and passed_report["buyer_signoff_required"] is True, "validator must preserve buyer-signoff boundary")
        dataset.write_bytes(b"tampered-after-manifest")
        tampered_report = validator.validate_delivery(completed_manifest, dataset, production_log)
        require(tampered_report["status"] == "failed", "tampered Gate 1 package must fail the validator")

    archive_sha = sha256(ARCHIVE_PATH.read_bytes())
    sidecar_parts = SIDECAR_PATH.read_text(encoding="utf-8").strip().split()
    require(sidecar_parts == [archive_sha, ARCHIVE_PATH.name], "buyer kit archive sidecar mismatch")
    expected_names = {f"{ARCHIVE_ROOT}/{relative}" for relative in payloads}
    with zipfile.ZipFile(ARCHIVE_PATH) as archive:
        names = set(archive.namelist())
        require(names == expected_names, "buyer kit ZIP membership mismatch")
        require(archive.testzip() is None, "buyer kit ZIP CRC verification failed")
        for relative, data in payloads.items():
            require(archive.read(f"{ARCHIVE_ROOT}/{relative}") == data, f"buyer kit ZIP payload mismatch: {relative}")

    print(f"PASS buyer pilot kit (11 blank templates + executable Gate 1 validator; archive SHA-256 {archive_sha})")


if __name__ == "__main__":
    main()
