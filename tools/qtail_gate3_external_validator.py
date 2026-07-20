#!/usr/bin/env python3
"""Validate buyer-owned Gate 3 trial, cost, and sign-off evidence.

The validator checks completeness and thresholds but cannot authenticate people,
hardware, invoices, URLs, or signatures. A passing report is therefore ready
for operator review, never automatic buyer approval.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse


TRIAL_FIELDS = {
    "pilot_id", "task_id", "robot_model", "robot_serial", "site_id",
    "session_date", "condition", "episode_id", "policy_sha256",
    "dataset_manifest_sha256", "success", "safety_stop", "collision",
    "operator_name", "evidence_url", "notes",
}
COST_FIELDS = {
    "pilot_id", "condition", "cost_category", "description", "quantity",
    "unit_cost_cny", "actual_cost_cny", "invoice_reference", "evidence_url",
}
CONDITIONS = {"baseline", "qtail"}


def now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_csv(path: Path, required: set[str]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path.name} missing columns: {', '.join(sorted(missing))}")
        rows = list(reader)
    if not rows:
        raise ValueError(f"{path.name} has no data rows")
    return rows


def parse_bool(value: str, *, field: str, row_number: int) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    raise ValueError(f"row {row_number}: {field} must be true/false")


def is_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdefABCDEF" for char in value)


def is_absolute_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def validate_trials(rows: list[dict[str, str]]) -> tuple[dict, list[str]]:
    errors: list[str] = []
    counts: Counter[tuple[str, str]] = Counter()
    successes: Counter[str] = Counter()
    dates: dict[str, set[str]] = defaultdict(set)
    pilot_ids: set[str] = set()
    task_ids: set[str] = set()
    safety_stops = 0
    collisions = 0
    seen_episodes: set[tuple[str, str]] = set()
    for index, row in enumerate(rows, start=2):
        try:
            condition = row["condition"].strip().lower()
            if condition not in CONDITIONS:
                errors.append(f"row {index}: condition must be baseline or qtail")
                continue
            required_values = ["pilot_id", "task_id", "robot_model", "robot_serial", "site_id", "session_date", "episode_id", "operator_name"]
            for field in required_values:
                if not row[field].strip():
                    errors.append(f"row {index}: {field} is required")
            if not is_sha256(row["policy_sha256"].strip()):
                errors.append(f"row {index}: policy_sha256 is invalid")
            if not is_sha256(row["dataset_manifest_sha256"].strip()):
                errors.append(f"row {index}: dataset_manifest_sha256 is invalid")
            if not is_absolute_http_url(row["evidence_url"].strip()):
                errors.append(f"row {index}: evidence_url must be absolute http(s)")
            success = parse_bool(row["success"], field="success", row_number=index)
            safety_stop = parse_bool(row["safety_stop"], field="safety_stop", row_number=index)
            collision = parse_bool(row["collision"], field="collision", row_number=index)
            episode_key = (row["pilot_id"].strip(), row["episode_id"].strip())
            if episode_key in seen_episodes:
                errors.append(f"row {index}: duplicate pilot_id/episode_id")
            seen_episodes.add(episode_key)
            pilot_ids.add(row["pilot_id"].strip())
            task = row["task_id"].strip()
            task_ids.add(task)
            dates[task].add(row["session_date"].strip())
            counts[(task, condition)] += 1
            successes[condition] += int(success)
            safety_stops += int(safety_stop)
            collisions += int(collision)
        except ValueError as error:
            errors.append(str(error))
    if len(pilot_ids) != 1:
        errors.append("trial file must contain exactly one pilot_id")
    if not 3 <= len(task_ids) <= 5:
        errors.append(f"expected 3-5 task_id values, found {len(task_ids)}")
    for task in sorted(task_ids):
        for condition in sorted(CONDITIONS):
            if counts[(task, condition)] < 30:
                errors.append(f"{task}/{condition}: requires >=30 trials, found {counts[(task, condition)]}")
        if len(dates[task]) < 2:
            errors.append(f"{task}: requires trials on >=2 dates, found {len(dates[task])}")
    return {
        "pilot_ids": sorted(pilot_ids),
        "task_ids": sorted(task_ids),
        "trial_counts": {f"{task}/{condition}": counts[(task, condition)] for task in sorted(task_ids) for condition in sorted(CONDITIONS)},
        "successes": dict(successes),
        "safety_stops": safety_stops,
        "collisions": collisions,
        "dates_per_task": {task: sorted(dates[task]) for task in sorted(task_ids)},
    }, errors


def validate_costs(rows: list[dict[str, str]], pilot_id: str, trial_summary: dict) -> tuple[dict, list[str]]:
    errors: list[str] = []
    totals = Counter()
    invoice_rows = Counter()
    for index, row in enumerate(rows, start=2):
        condition = row["condition"].strip().lower()
        if row["pilot_id"].strip() != pilot_id:
            errors.append(f"cost row {index}: pilot_id does not match trials")
        if condition not in CONDITIONS:
            errors.append(f"cost row {index}: condition must be baseline or qtail")
            continue
        try:
            quantity = float(row["quantity"])
            unit_cost = float(row["unit_cost_cny"])
            actual_cost = float(row["actual_cost_cny"])
            if quantity <= 0 or unit_cost < 0 or actual_cost <= 0:
                errors.append(f"cost row {index}: quantity and actual cost must be positive")
            expected = quantity * unit_cost
            if abs(expected - actual_cost) > max(0.01, actual_cost * 0.01):
                errors.append(f"cost row {index}: quantity × unit cost differs from actual cost by >1%")
            if not row["invoice_reference"].strip():
                errors.append(f"cost row {index}: invoice_reference is required")
            else:
                invoice_rows[condition] += 1
            if not is_absolute_http_url(row["evidence_url"].strip()):
                errors.append(f"cost row {index}: evidence_url must be absolute http(s)")
            totals[condition] += actual_cost
        except ValueError:
            errors.append(f"cost row {index}: quantity/unit_cost_cny/actual_cost_cny must be numeric")
    unit_costs = {}
    for condition in sorted(CONDITIONS):
        successes = trial_summary["successes"].get(condition, 0)
        if successes <= 0:
            errors.append(f"{condition}: no successful real-robot trials for unit-cost calculation")
            unit_costs[condition] = None
        else:
            unit_costs[condition] = totals[condition] / successes
        if invoice_rows[condition] == 0:
            errors.append(f"{condition}: no invoice-backed cost rows")
    reduction = None
    if unit_costs.get("baseline") and unit_costs.get("qtail") is not None:
        reduction = (unit_costs["baseline"] - unit_costs["qtail"]) / unit_costs["baseline"] * 100.0
        if reduction < 20.0:
            errors.append(f"actual unit effective-success cost reduction is {reduction:.2f}%, below 20%")
    return {
        "actual_cost_cny": dict(totals),
        "successful_trials": trial_summary["successes"],
        "unit_effective_success_cost_cny": unit_costs,
        "unit_cost_reduction_pct": reduction,
        "invoice_rows": dict(invoice_rows),
    }, errors


def validate_signoff(signoff: dict, pilot_id: str) -> list[str]:
    errors = []
    if signoff.get("pilot_id") != pilot_id:
        errors.append("signoff pilot_id does not match trials")
    for field in ("buyer_company", "buyer_owner", "hardware_safety_owner", "procurement_owner", "contract_reference", "signed_at"):
        value = signoff.get(field)
        if not isinstance(value, str) or not value.strip() or value.startswith("REPLACE_"):
            errors.append(f"signoff {field} is required and cannot be a template placeholder")
    if signoff.get("accepted") is not True:
        errors.append("signoff accepted must be true")
    if not is_absolute_http_url(str(signoff.get("signoff_evidence_url", ""))):
        errors.append("signoff_evidence_url must be absolute http(s)")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate buyer-owned Q-Tail Gate 3 evidence.")
    parser.add_argument("--trials", type=Path, required=True)
    parser.add_argument("--costs", type=Path, required=True)
    parser.add_argument("--signoff", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("gate3_external_validation_report.json"))
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args()
    trial_path, cost_path, signoff_path = (path.resolve() for path in (args.trials, args.costs, args.signoff))
    try:
        trials = load_csv(trial_path, TRIAL_FIELDS)
        trial_summary, trial_errors = validate_trials(trials)
        pilot_id = trial_summary["pilot_ids"][0] if len(trial_summary["pilot_ids"]) == 1 else ""
        costs = load_csv(cost_path, COST_FIELDS)
        cost_summary, cost_errors = validate_costs(costs, pilot_id, trial_summary)
        signoff = json.loads(signoff_path.read_text(encoding="utf-8"))
        signoff_errors = validate_signoff(signoff, pilot_id)
        errors = trial_errors + cost_errors + signoff_errors
    except (ValueError, OSError, json.JSONDecodeError) as error:
        trial_summary, cost_summary = {}, {}
        signoff = {}
        errors = [str(error)]
    report = {
        "gate": 3,
        "status": "ready_for_operator_review" if not errors else "requirements_not_met",
        "generated_at": now(),
        "automated_checks_passed": not errors,
        "buyer_gate_passed": False,
        "trial_summary": trial_summary,
        "cost_summary": cost_summary,
        "signoff_summary": {key: signoff.get(key) for key in ("pilot_id", "buyer_company", "buyer_owner", "hardware_safety_owner", "procurement_owner", "contract_reference", "accepted", "signed_at")},
        "errors": errors,
        "input_sha256": {
            "trials": sha256_file(trial_path) if trial_path.exists() else None,
            "costs": sha256_file(cost_path) if cost_path.exists() else None,
            "signoff": sha256_file(signoff_path) if signoff_path.exists() else None,
        },
        "operator_review_required": True,
        "claim_boundary": "Passing automated checks does not authenticate hardware execution, people, invoices, URLs, signatures, or contract enforceability.",
    }
    out = args.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.require_pass and errors:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
