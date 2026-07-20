#!/usr/bin/env python3
"""Create a MetaWorld benchmark anchor for Q-Tail evaluation.

This adapter statically parses the local MetaWorld task definitions. It avoids
importing MetaWorld or MuJoCo so it can run in lightweight CI and product demos.
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_DICT = ROOT / "Metaworld" / "metaworld" / "env_dict.py"
DEFAULT_OUT_CSV = ROOT / "data" / "metaworld_benchmark_anchor.csv"
DEFAULT_AUDIT = ROOT / "results" / "qtail_metaworld_anchor" / "source_audit.json"


def extract_assignment_list(text: str, name: str) -> list[str]:
    pattern = rf"{name}\s*=\s*_get_env_dict\(\s*(\[[\s\S]*?\])\s*\)"
    match = re.search(pattern, text)
    if not match:
        return []
    return list(ast.literal_eval(match.group(1)))


def extract_train_test(text: str, name: str) -> tuple[list[str], list[str]]:
    pattern = rf"{name}\s*=\s*_get_train_test_env_dict\(\s*train_env_names=(\[[\s\S]*?\]),\s*test_env_names=(\[[\s\S]*?\]),\s*\)"
    match = re.search(pattern, text)
    if not match:
        return [], []
    return list(ast.literal_eval(match.group(1))), list(ast.literal_eval(match.group(2)))


def extract_all_envs(text: str) -> list[str]:
    match = re.search(r"ALL_V3_ENVIRONMENTS\s*=\s*_get_env_dict\(\s*(\[[\s\S]*?\])\s*\)", text)
    if not match:
        raise ValueError("Could not find ALL_V3_ENVIRONMENTS in env_dict.py")
    return list(ast.literal_eval(match.group(1)))


def task_family(task: str) -> str:
    if any(token in task for token in ["door", "drawer", "window", "faucet", "button", "handle", "dial"]):
        return "articulated_object"
    if any(token in task for token in ["pick", "place", "insert", "assembly", "bin", "box", "shelf"]):
        return "pick_place_insert"
    if any(token in task for token in ["push", "pull", "sweep", "soccer", "basketball", "hammer", "stick"]):
        return "contact_dynamics"
    return "reach_navigation"


def build_rows(env_dict_path: Path) -> tuple[list[dict], dict]:
    text = env_dict_path.read_text(encoding="utf-8")
    all_envs = extract_all_envs(text)
    mt10 = set(extract_assignment_list(text, "MT10_V3"))
    mt25 = set(extract_assignment_list(text, "MT25_V3"))
    ml10_train, ml10_test = extract_train_test(text, "ML10_V3")
    ml45_train, ml45_test = extract_train_test(text, "ML45_V3")
    ml_test = set(ml10_test + ml45_test)

    rows = []
    for idx, env_name in enumerate(all_envs):
        in_mt10 = env_name in mt10
        in_mt25 = env_name in mt25
        is_ml_test = env_name in ml_test
        family = task_family(env_name)
        # Count is an evaluation allocation proxy: canonical MT10 tasks are
        # common, MT25 tasks are medium, and ML held-out tasks are rare tails.
        count = 1800 if in_mt10 else 850 if in_mt25 else 260
        if is_ml_test:
            count = 120
        difficulty = 0.28 + 0.18 * (not in_mt10) + 0.18 * (not in_mt25) + 0.22 * is_ml_test
        if family == "contact_dynamics":
            difficulty += 0.08
        if family == "pick_place_insert":
            difficulty += 0.05
        difficulty = min(0.95, difficulty)
        success_rate = max(0.24, 0.86 - 0.46 * difficulty)
        group = "tail" if is_ml_test or not in_mt25 else "medium" if not in_mt10 else "head"
        rows.append(
            {
                "dataset": "MetaWorld local benchmark task suite",
                "task": env_name,
                "count": count,
                "success_rate": round(success_rate, 4),
                "difficulty": round(difficulty, 4),
                "group": group,
                "family": family,
                "benchmark_membership": "|".join(
                    [
                        label
                        for label, present in [
                            ("MT10", in_mt10),
                            ("MT25", in_mt25),
                            ("MT50", True),
                            ("ML10-test", env_name in ml10_test),
                            ("ML45-test", env_name in ml45_test),
                        ]
                        if present
                    ]
                ),
                "source_url": "local:Metaworld/metaworld/env_dict.py",
                "evidence": "static MetaWorld V3 task definitions; MT50/MT10/MT25/ML10/ML45 splits",
                "adapter_method": "local_benchmark_task_space_anchor",
            }
        )

    audit = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_path": str(env_dict_path),
        "row_count": len(rows),
        "extracted": {
            "all_v3_tasks": len(all_envs),
            "mt10_tasks": len(mt10),
            "mt25_tasks": len(mt25),
            "ml10_train_tasks": len(ml10_train),
            "ml10_test_tasks": len(ml10_test),
            "ml45_train_tasks": len(ml45_train),
            "ml45_test_tasks": len(ml45_test),
        },
        "claim_boundary": [
            "Rows represent benchmark task-space coverage, not collected trajectory counts.",
            "Counts, success_rate, and difficulty are deterministic evaluation priors from benchmark membership.",
            "This anchor validates rare-task allocation behavior over a canonical manipulation benchmark taxonomy.",
        ],
    }
    return rows, audit


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build local MetaWorld benchmark anchor CSV.")
    parser.add_argument("--env-dict", default=str(DEFAULT_ENV_DICT), help="Path to MetaWorld env_dict.py.")
    parser.add_argument("--out-csv", default=str(DEFAULT_OUT_CSV), help="Output CSV for qtail_data_engine.py.")
    parser.add_argument("--audit", default=str(DEFAULT_AUDIT), help="Output audit JSON.")
    args = parser.parse_args()

    rows, audit = build_rows(Path(args.env_dict))
    out_csv = Path(args.out_csv)
    audit_path = Path(args.audit)
    write_csv(out_csv, rows)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit["output_csv"] = str(out_csv)
    audit_path.write_text(json.dumps(audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"metaworld anchor complete: rows={len(rows)}, csv={out_csv}, audit={audit_path}")


if __name__ == "__main__":
    main()
