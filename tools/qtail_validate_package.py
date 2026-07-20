#!/usr/bin/env python3
"""Validate a Q-Tail customer evaluation package."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def resolve_artifact(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def validate(report_path: Path, root: Path, require_pass: bool = True) -> dict:
    errors: list[str] = []
    report = json.loads(report_path.read_text(encoding="utf-8"))

    for key in ["input", "pt_source", "same_budget_audit", "decision", "evaluation", "artifacts"]:
        if key not in report:
            errors.append(f"missing top-level key: {key}")

    evaluation = report.get("evaluation", {})
    decision = report.get("decision", {})
    audit = report.get("same_budget_audit", {})

    for key in ["source_data_metrics", "qtail_synthetic_metrics", "gains", "pass_gate", "test_passed", "per_task"]:
        if key not in evaluation:
            errors.append(f"missing evaluation key: {key}")

    if require_pass and not evaluation.get("test_passed"):
        errors.append("evaluation test_passed is false")
    if require_pass and decision.get("winner") != "qtail_synthetic":
        errors.append(f"winner is not qtail_synthetic: {decision.get('winner')}")
    if decision.get("passed") != evaluation.get("test_passed"):
        errors.append("decision.passed does not match evaluation.test_passed")

    if not audit.get("same_task_set"):
        errors.append("same_budget_audit.same_task_set is false")
    if not audit.get("allocation_sums_valid"):
        errors.append("same_budget_audit allocation sums are invalid")
    if audit.get("same_total_budget") != report.get("synthetic_budget"):
        errors.append("same_total_budget does not match synthetic_budget")

    gains = evaluation.get("gains", {})
    if require_pass:
        for metric in ["tail_success", "cvar20", "tail_data_share"]:
            if gains.get(metric, 0) <= 0:
                errors.append(f"non-positive required gain: {metric}")

    for name, value in report.get("artifacts", {}).items():
        artifact_path = resolve_artifact(root, value)
        if not artifact_path.exists():
            errors.append(f"missing artifact {name}: {artifact_path}")

    per_task = evaluation.get("per_task", [])
    if per_task and audit.get("profile_count") != len(per_task):
        errors.append("profile_count does not match per_task length")

    return {
        "report_path": str(report_path),
        "valid": not errors,
        "errors": errors,
        "winner": decision.get("winner"),
        "test_passed": evaluation.get("test_passed"),
        "profile_count": audit.get("profile_count"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a Q-Tail evaluation package report.")
    parser.add_argument("report", help="Path to qtail_data_engine_report.json.")
    parser.add_argument("--root", default=str(ROOT), help="Repository/package root used for relative artifact paths.")
    parser.add_argument("--allow-inconclusive", action="store_true", help="Do not require Q-Tail to pass the decision gate.")
    args = parser.parse_args()

    result = validate(Path(args.report), Path(args.root), require_pass=not args.allow_inconclusive)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if not result["valid"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
