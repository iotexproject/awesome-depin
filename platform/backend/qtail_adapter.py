from __future__ import annotations

import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path

from trajectory_delivery import CATALOG_FILENAME, DELIVERY_PRODUCT, build_trajectory_batch


REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS = REPO_ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))


def _fake_package(input_path: Path, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "product": "qtail_long_tail_allocation_plan",
        "claim_boundary": "Allocation and scenario specifications; not trainable robot trajectories.",
        "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
        "test_fixture": True,
    }
    manifest_path = out_dir / "package_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    plan_path = out_dir / "qtail_service_synthetic_plan.csv"
    plan_path.write_text(input_path.read_text(encoding="utf-8"), encoding="utf-8")
    zip_path = out_dir / "qtail_delivery_package.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(input_path, arcname=input_path.name)
        archive.write(manifest_path, arcname=manifest_path.name)
    return {
        "package_zip": str(zip_path),
        "package_manifest": str(manifest_path),
        "synthetic_plan": str(plan_path),
        "effect_summary": {"test_fixture": True},
    }


def generate_package(
    input_path: Path,
    out_dir: Path,
    synthetic_budget: float,
    top_k: int = 128,
    *,
    delivery_product: str = "allocation_plan",
    trajectory_count: int | None = None,
    catalog_dir: Path | None = None,
) -> dict:
    if os.environ.get("QTAIL_FAKE_GENERATOR") == "1":
        allocation_delivery = _fake_package(input_path, out_dir / "allocation")
    else:
        from qtail_data_engine import DEFAULT_PT_SOURCE
        from qtail_openx_service_model import build_service_package

        strong_report = REPO_ROOT / "results/openx_strong_training/openx_demo_training_report.json"
        strong_rows = REPO_ROOT / "results/openx_strong_training/openx_shard_training_rows.csv"
        allocation_delivery = build_service_package(
            input_path=input_path,
            out_dir=out_dir / "allocation",
            training_report_path=strong_report,
            training_rows_path=strong_rows,
            synthetic_budget=synthetic_budget,
            pt_source=DEFAULT_PT_SOURCE,
            top_k=top_k,
            require_pass=False,
        )
    if delivery_product != DELIVERY_PRODUCT:
        return allocation_delivery
    if trajectory_count is None:
        raise RuntimeError("trajectory_count is required for simulation trajectory delivery")
    source_dir = catalog_dir or Path(os.environ.get("QTAIL_SYNTHETIC_CATALOG_DIR", out_dir / "catalog"))
    return build_trajectory_batch(
        input_path=input_path,
        out_dir=out_dir,
        allocation_delivery=allocation_delivery,
        trajectory_count=int(trajectory_count),
        catalog_path=source_dir / CATALOG_FILENAME,
    )
