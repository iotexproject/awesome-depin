#!/usr/bin/env python3
"""Build public embodied-AI anchor data for the Q-Tail data engine.

The adapter does not download full trajectory datasets. It reads official
public project pages, extracts aggregate metadata, and expands those aggregates
into deterministic task buckets that the Q-Tail data engine can evaluate with
the same protocol used for user-provided CSV files.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import ssl
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_CSV = ROOT / "data" / "embodied_public_anchor_real.csv"
DEFAULT_AUDIT_DIR = ROOT / "results" / "qtail_public_anchor_adapter"


@dataclass(frozen=True)
class PublicSource:
    key: str
    name: str
    url: str


SOURCES = [
    PublicSource("openx", "Google DeepMind Open X-Embodiment / RT-X", "https://robotics-transformer-x.github.io/"),
    PublicSource("droid", "DROID real robot manipulation dataset", "https://droid-dataset.github.io/"),
    PublicSource("habitat3", "Meta AI Habitat 3.0", "https://aihabitat.org/habitat3/"),
]


def fetch_text(url: str, cache_path: Path, refresh: bool = False) -> tuple[str, str]:
    if cache_path.exists() and not refresh:
        return cache_path.read_text(encoding="utf-8", errors="replace"), "cache"

    request = Request(url, headers={"User-Agent": "Q-Tail-public-anchor-adapter/0.1"})
    context = ssl._create_unverified_context()
    with urlopen(request, timeout=30, context=context) as response:
        text = response.read().decode("utf-8", errors="replace")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(text, encoding="utf-8")
    return text, "network"


def clean_text(raw_html: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", raw_html, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def first_number(pattern: str, text: str, default: float | None = None) -> float | None:
    match = re.search(pattern, text, flags=re.I)
    if not match:
        return default
    raw = match.group(1).replace(",", "").strip()
    scale = 1.0
    if raw.lower().endswith("k"):
        scale = 1_000.0
        raw = raw[:-1]
    elif raw.lower().endswith("m"):
        scale = 1_000_000.0
        raw = raw[:-1]
    try:
        return float(raw) * scale
    except ValueError:
        return default


def task_buckets(
    dataset: str,
    source_url: str,
    prefix: str,
    total_count: float,
    bucket_count: int,
    evidence: str,
    method: str,
    exponent: float,
    task_descriptor: str,
) -> list[dict[str, str | float]]:
    ranks = list(range(1, bucket_count + 1))
    weights = [1.0 / (rank**exponent) for rank in ranks]
    total_weight = sum(weights)
    rows: list[dict[str, str | float]] = []
    for rank, weight in zip(ranks, weights):
        share = weight / total_weight
        rarity = (rank - 1) / max(1, bucket_count - 1)
        group = "head" if rank <= max(2, math.ceil(bucket_count * 0.18)) else "tail" if rank > math.floor(bucket_count * 0.68) else "medium"
        difficulty = min(0.94, 0.22 + 0.68 * rarity)
        success = max(0.24, 0.86 - 0.46 * rarity)
        rows.append(
            {
                "dataset": dataset,
                "task": f"{prefix}_{rank:02d}_{task_descriptor}",
                "count": round(total_count * share, 4),
                "success_rate": round(success, 4),
                "difficulty": round(difficulty, 4),
                "group": group,
                "source_url": source_url,
                "evidence": evidence,
                "adapter_method": method,
            }
        )
    return rows


def build_openx_rows(text: str, source: PublicSource) -> tuple[list[dict], dict]:
    trajectories = first_number(r"contains\s+([0-9.]+M)\+?\s+real robot trajectories", text, 1_000_000)
    robots = first_number(r"from\s+([0-9]+)\s+different robots", text, 22)
    institutions = first_number(r"([0-9]+)\s+institutions", text, 21)
    skills = first_number(r"([0-9]+)\s+skills", text, 527)
    tasks = first_number(r"\(([0-9]+)\s+tasks\)", text, 160_266)
    datasets = first_number(r"pooling\s+([0-9]+)\s+existing robot datasets", text, 60)
    labs = first_number(r"from\s+([0-9]+)\s+robotic research labs", text, 34)
    evidence = (
        f"official aggregate: {int(trajectories or 0)}+ trajectories, {int(robots or 0)} robots, "
        f"{int(skills or 0)} skills, {int(tasks or 0)} tasks, {int(datasets or 0)} datasets"
    )
    rows = task_buckets(
        dataset=source.name,
        source_url=source.url,
        prefix="openx_skill_bucket",
        total_count=float(trajectories or 1_000_000),
        bucket_count=64,
        evidence=evidence,
        method="aggregate_zipf_expansion_from_official_counts",
        exponent=1.08,
        task_descriptor="cross_embodiment_skill",
    )
    return rows, {
        "trajectories": trajectories,
        "robots": robots,
        "institutions": institutions,
        "skills": skills,
        "tasks": tasks,
        "datasets": datasets,
        "labs": labs,
        "evidence": evidence,
    }


def build_droid_rows(text: str, source: PublicSource) -> tuple[list[dict], dict]:
    trajectories = first_number(r"with\s+([0-9.]+k)\s+demonstration trajectories", text, 76_000)
    hours = first_number(r"or\s+([0-9]+)h\s+of interaction data", text, 350)
    scenes = first_number(r"across\s+([0-9]+)\s+scenes", text, 564)
    tasks = first_number(r"and\s+([0-9]+)\s+tasks", text, 86)
    collectors = first_number(r"by\s+([0-9]+)\s+data collectors", text, 50)
    institutions = first_number(r"across all\s+([0-9]+)\s+institutions", text, 13)
    evidence = (
        f"official aggregate: {int(trajectories or 0)} trajectories, {int(hours or 0)} hours, "
        f"{int(scenes or 0)} scenes, {int(tasks or 0)} tasks, {int(collectors or 0)} collectors"
    )
    rows = task_buckets(
        dataset=source.name,
        source_url=source.url,
        prefix="droid_task_bucket",
        total_count=float(trajectories or 76_000),
        bucket_count=int(min(48, max(12, tasks or 24))),
        evidence=evidence,
        method="aggregate_zipf_expansion_from_official_counts",
        exponent=1.16,
        task_descriptor="in_the_wild_manipulation",
    )
    return rows, {
        "trajectories": trajectories,
        "hours": hours,
        "scenes": scenes,
        "tasks": tasks,
        "collectors": collectors,
        "institutions": institutions,
        "evidence": evidence,
    }


def build_habitat_rows(text: str, source: PublicSource) -> tuple[list[dict], dict]:
    task_names = []
    if re.search(r"Social Navigation", text, flags=re.I):
        task_names.append(("habitat3_social_navigation", "finding/following humanoid while maintaining safe distance"))
    if re.search(r"Social Rearrangement", text, flags=re.I):
        task_names.append(("habitat3_social_rearrangement", "collaborative object rearrangement with humanoid"))
    if not task_names:
        task_names = [("habitat3_hri_benchmark_task", "human-robot interaction benchmark")]

    evidence = "official qualitative benchmark tasks: " + ", ".join(name for name, _ in task_names)
    rows = []
    for idx, (task_id, descriptor) in enumerate(task_names, start=1):
        rows.append(
            {
                "dataset": source.name,
                "task": task_id,
                "count": 1.0,
                "success_rate": round(0.60 - 0.08 * (idx - 1), 4),
                "difficulty": round(0.58 + 0.16 * (idx - 1), 4),
                "group": "medium" if idx == 1 else "tail",
                "source_url": source.url,
                "evidence": f"{evidence}; descriptor: {descriptor}",
                "adapter_method": "qualitative_benchmark_task_anchor_no_public_trajectory_count",
            }
        )
    return rows, {"benchmark_tasks": [name for name, _ in task_names], "evidence": evidence}


def build(refresh: bool, out_csv: Path, audit_dir: Path) -> dict:
    audit_dir.mkdir(parents=True, exist_ok=True)
    page_dir = audit_dir / "source_pages"
    all_rows: list[dict] = []
    audit: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "claim_boundary": [
            "Rows are deterministic task buckets derived from official aggregate metadata, not raw trajectory records.",
            "Success and difficulty values are modeling priors used to run a same-protocol data allocation test.",
            "Full policy-training validation still requires exported trajectory summaries or benchmark runs.",
        ],
        "sources": [],
    }

    builders = {"openx": build_openx_rows, "droid": build_droid_rows, "habitat3": build_habitat_rows}
    for source in SOURCES:
        cache_path = page_dir / f"{source.key}.html"
        raw, fetch_method = fetch_text(source.url, cache_path, refresh=refresh)
        text = clean_text(raw)
        rows, extracted = builders[source.key](text, source)
        all_rows.extend(rows)
        audit["sources"].append(
            {
                "key": source.key,
                "name": source.name,
                "url": source.url,
                "fetch_method": fetch_method,
                "cache_path": str(cache_path),
                "row_count": len(rows),
                "extracted": extracted,
            }
        )

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(all_rows[0].keys()))
        writer.writeheader()
        writer.writerows(all_rows)

    audit["output_csv"] = str(out_csv)
    audit["row_count"] = len(all_rows)
    audit_path = audit_dir / "source_audit.json"
    audit_path.write_text(json.dumps(audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    audit["audit_path"] = str(audit_path)
    return audit


def main() -> None:
    parser = argparse.ArgumentParser(description="Build public embodied-AI anchor CSV for Q-Tail evaluation.")
    parser.add_argument("--out-csv", default=str(DEFAULT_OUT_CSV), help="Output CSV consumed by qtail_data_engine.py.")
    parser.add_argument("--audit-dir", default=str(DEFAULT_AUDIT_DIR), help="Output directory for source audit and cached pages.")
    parser.add_argument("--refresh", action="store_true", help="Refresh official pages instead of using cache.")
    args = parser.parse_args()

    try:
        audit = build(refresh=args.refresh, out_csv=Path(args.out_csv), audit_dir=Path(args.audit_dir))
    except Exception as exc:
        print(f"public anchor adapter failed: {exc}", file=sys.stderr)
        raise

    print(
        "public anchor adapter complete: "
        f"rows={audit['row_count']}, "
        f"csv={audit['output_csv']}, "
        f"audit={audit['audit_path']}"
    )


if __name__ == "__main__":
    main()
