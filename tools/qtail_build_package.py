#!/usr/bin/env python3
"""Build a complete Q-Tail evaluation package from one input CSV."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from qtail_data_engine import DEFAULT_PT_SOURCE, run as run_engine  # noqa: E402
from qtail_validate_package import validate as validate_package  # noqa: E402


def build_package(
    *,
    input_path: Path,
    out_dir: Path,
    synthetic_budget: float,
    pt_source: Path,
    top_k: int,
    source_audit: Path | None,
    require_pass: bool,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = run_engine(
        input_path=input_path,
        out_dir=out_dir,
        synthetic_budget=synthetic_budget,
        pt_source=pt_source,
        top_k=top_k,
        source_audit=source_audit,
    )
    report_path = out_dir / "qtail_data_engine_report.json"
    validation = validate_package(report_path, ROOT, require_pass=require_pass)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "package_type": "qtail_data_engine_evaluation_package",
        "input_csv": str(input_path),
        "output_dir": str(out_dir),
        "report": str(report_path),
        "synthetic_data": report["artifacts"]["qtail_synthetic_data"],
        "task_profiles": report["artifacts"]["task_profiles"],
        "per_task_comparison": report["artifacts"]["per_task_comparison"],
        "winner": report["decision"]["winner"],
        "test_passed": report["decision"]["passed"],
        "same_budget_audit": report["same_budget_audit"],
        "validation": validation,
    }
    manifest_path = out_dir / "package_manifest.json"
    manifest["manifest"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and validate a Q-Tail evaluation package from a CSV.")
    parser.add_argument("--input", required=True, help="User/customer CSV input.")
    parser.add_argument("--out", required=True, help="Output package directory.")
    parser.add_argument("--synthetic-budget", type=float, default=100_000.0, help="Same synthetic budget for source and Q-Tail allocations.")
    parser.add_argument("--pt-source", default=str(DEFAULT_PT_SOURCE), help="PT source CSV.")
    parser.add_argument("--top-k", type=int, default=128, help="Maximum task/scenario profiles.")
    parser.add_argument("--source-audit", default="", help="Optional source audit JSON.")
    parser.add_argument("--allow-inconclusive", action="store_true", help="Build package even if Q-Tail does not pass gate.")
    args = parser.parse_args()

    manifest = build_package(
        input_path=Path(args.input),
        out_dir=Path(args.out),
        synthetic_budget=args.synthetic_budget,
        pt_source=Path(args.pt_source),
        top_k=args.top_k,
        source_audit=Path(args.source_audit) if args.source_audit else None,
        require_pass=not args.allow_inconclusive,
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    if not manifest["validation"]["valid"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
