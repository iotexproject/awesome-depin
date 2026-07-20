from __future__ import annotations

import csv
import hashlib
import io
import json
import shutil
import struct
import tarfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path


CATALOG_FILENAME = "qtail-gate1-metaworld-sawyer-v0.1.0.tar.gz"
CATALOG_BYTES = 56_447_787
CATALOG_SHA256 = "c58b39d83a1a9f9d72533ed2f33d8280bbf7fee98e28b3c082fca116894d2fb0"
CATALOG_MANIFEST_SHA256 = "003d5d62c92237412f86d72e796c4a5570e3a9760b1d40fee8c0f7f826f3c13a"
SUPPORTED_TASKS = ("reach-v3", "button-press-v3", "pick-place-v3")
DELIVERY_PRODUCT = "simulation_trajectory_batch"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def supported_tasks_from_csv(csv_text: str) -> list[str]:
    try:
        reader = csv.DictReader(io.StringIO(csv_text))
        task_column = next((name for name in (reader.fieldnames or []) if name.strip().lower() in {"task", "task_id"}), None)
        if not task_column:
            return []
        tasks: list[str] = []
        for row in reader:
            task = str(row.get(task_column) or "").strip()
            if task and task not in tasks:
                tasks.append(task)
        return tasks
    except (csv.Error, UnicodeError):
        return []


def validate_trajectory_request(payload: dict) -> dict:
    try:
        trajectory_count = int(payload.get("trajectory_count"))
        frequency = float(payload.get("control_frequency_hz"))
    except (TypeError, ValueError) as exc:
        raise ValueError("仿真轨迹批次必须填写有效的 trajectory_count 和控制频率") from exc
    if trajectory_count < 1 or trajectory_count > 64:
        raise ValueError("仿真轨迹批次支持 1–64 条 trajectory_count")
    robot = str(payload.get("robot_model") or "").lower()
    backend = str(payload.get("production_backend") or "").lower()
    training_format = str(payload.get("training_format") or "")
    sensors = str(payload.get("sensors") or "").lower()
    if "sawyer" not in robot or "metaworld" not in robot:
        raise ValueError("当前按需轨迹后端仅支持 Sawyer / MetaWorld 构型")
    if "mujoco" not in backend or "metaworld" not in backend:
        raise ValueError("当前按需轨迹后端必须选择 MuJoCo / MetaWorld")
    if abs(frequency - 20.0) > 1e-9:
        raise ValueError("当前 Sawyer / MetaWorld 轨迹源固定为 20 Hz")
    if "RLDS" not in training_format:
        raise ValueError("当前按需轨迹批次必须包含 RLDS 训练格式")
    if "rgb" not in sensors or ("state" not in sensors and "状态" not in sensors):
        raise ValueError("当前轨迹源的传感器契约必须包含 RGB 与状态观测")
    tasks = supported_tasks_from_csv(str(payload.get("csv_text") or ""))
    if not tasks:
        raise ValueError("轨迹任务 CSV 必须包含 task/task_id 及至少一个任务")
    unsupported = [task for task in tasks if task not in SUPPORTED_TASKS]
    if unsupported:
        raise ValueError(f"当前轨迹源不支持任务：{', '.join(unsupported)}")
    if trajectory_count < len(tasks):
        raise ValueError("trajectory_count 不能小于请求中的任务数量")
    return {"trajectory_count": trajectory_count, "tasks": tasks}


def _member(archive: tarfile.TarFile, suffix: str) -> tarfile.TarInfo:
    matches = [item for item in archive.getmembers() if item.isfile() and (item.name == suffix or item.name.endswith("/" + suffix))]
    if len(matches) != 1:
        raise RuntimeError(f"Source catalog member mismatch for {suffix}: {len(matches)}")
    return matches[0]


def _member_bytes(archive: tarfile.TarFile, suffix: str) -> bytes:
    handle = archive.extractfile(_member(archive, suffix))
    if handle is None:
        raise RuntimeError(f"Source catalog member is unreadable: {suffix}")
    return handle.read()


def _plan_weights(plan_path: Path, tasks: list[str]) -> dict[str, float]:
    rows: dict[str, dict] = {}
    with plan_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            task = str(row.get("task_id") or row.get("task") or "").strip()
            if task:
                rows[task] = row
    weights: dict[str, float] = {}
    for task in tasks:
        row = rows.get(task, {})
        value = row.get("synthetic_count") or row.get("tail_score") or 1
        try:
            weights[task] = max(float(value), 1e-12)
        except (TypeError, ValueError):
            weights[task] = 1.0
    return weights


def _allocate(weights: dict[str, float], capacities: dict[str, int], total: int) -> dict[str, int]:
    tasks = list(weights)
    available = sum(capacities[task] for task in tasks)
    if total > available:
        raise RuntimeError(f"Requested {total} trajectories but only {available} source episodes match the requested tasks")
    allocation = {task: 1 for task in tasks}
    remaining = total - len(tasks)
    weight_sum = sum(weights.values())
    desired = {task: total * weights[task] / weight_sum for task in tasks}
    while remaining:
        candidates = [task for task in tasks if allocation[task] < capacities[task]]
        if not candidates:
            raise RuntimeError("Trajectory allocation exhausted source capacity")
        selected = max(
            candidates,
            key=lambda task: (desired[task] - allocation[task], weights[task], -tasks.index(task)),
        )
        allocation[selected] += 1
        remaining -= 1
    return allocation


def _selected_rows(index_rows: list[dict], allocation: dict[str, int], input_sha256: str) -> list[dict]:
    selected: list[dict] = []
    for task, count in allocation.items():
        rows = [dict(row) for row in index_rows if row.get("task") == task]
        if len(rows) < count:
            raise RuntimeError(f"Source trajectory index has only {len(rows)} episodes for {task}")
        offset = int(hashlib.sha256(f"{input_sha256}:{task}".encode()).hexdigest()[:16], 16) % len(rows)
        rotated = rows[offset:] + rows[:offset]
        selected.extend(rotated[:count])
    selected.sort(key=lambda row: int(row["episode_index"]))
    for delivery_index, row in enumerate(selected):
        row["source_episode_index"] = int(row.pop("episode_index"))
        row["delivery_episode_index"] = delivery_index
    return selected


def _copy_selected_tfrecord(source, destination: Path, selected_indices: set[int], expected_records: int) -> int:
    copied = 0
    record_index = 0
    with destination.open("wb") as output:
        while True:
            header = source.read(12)
            if not header:
                break
            if len(header) != 12:
                raise RuntimeError("Truncated TFRecord header in source catalog")
            length = struct.unpack("<Q", header[:8])[0]
            if length > 512 * 1024 * 1024:
                raise RuntimeError("Unreasonable TFRecord episode length in source catalog")
            payload_and_crc = source.read(length + 4)
            if len(payload_and_crc) != length + 4:
                raise RuntimeError("Truncated TFRecord episode in source catalog")
            if record_index in selected_indices:
                output.write(header)
                output.write(payload_and_crc)
                copied += 1
            record_index += 1
    if record_index != expected_records or copied != len(selected_indices):
        raise RuntimeError(
            f"TFRecord/index mismatch: source_records={record_index}, expected={expected_records}, copied={copied}"
        )
    return copied


def _write_json(path: Path, value: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_trajectory_batch(
    *,
    input_path: Path,
    out_dir: Path,
    allocation_delivery: dict,
    trajectory_count: int,
    catalog_path: Path,
    expected_catalog_bytes: int = CATALOG_BYTES,
    expected_catalog_sha256: str = CATALOG_SHA256,
    expected_manifest_sha256: str = CATALOG_MANIFEST_SHA256,
) -> dict:
    if not catalog_path.is_file():
        raise RuntimeError(f"Verified trajectory source catalog is missing: {catalog_path}")
    if catalog_path.stat().st_size != expected_catalog_bytes or sha256_file(catalog_path) != expected_catalog_sha256:
        raise RuntimeError("Trajectory source catalog failed exact byte/SHA-256 verification")
    input_sha256 = sha256_file(input_path)
    csv_text = input_path.read_text(encoding="utf-8")
    tasks = supported_tasks_from_csv(csv_text)
    plan_path = Path(allocation_delivery["synthetic_plan"]).resolve()
    if not plan_path.is_file():
        raise RuntimeError("Q-Tail allocation plan is missing before trajectory materialization")

    batch_dir = out_dir / "trajectory_batch"
    if batch_dir.exists():
        shutil.rmtree(batch_dir)
    batch_dir.mkdir(parents=True)
    rlds_dir = batch_dir / "rlds" / "0.1.0"
    rlds_dir.mkdir(parents=True)
    tfrecord_path = rlds_dir / "qtail_metaworld-selected.tfrecord-00000-of-00001"

    with tarfile.open(catalog_path, "r:gz") as archive:
        source_manifest_bytes = _member_bytes(archive, "package_manifest.json")
        if hashlib.sha256(source_manifest_bytes).hexdigest() != expected_manifest_sha256:
            raise RuntimeError("Trajectory source package manifest SHA-256 mismatch")
        source_manifest = json.loads(source_manifest_bytes)
        index_rows = json.loads(_member_bytes(archive, "trajectory_index.json"))
        capacities = {task: sum(1 for row in index_rows if row.get("task") == task) for task in tasks}
        weights = _plan_weights(plan_path, tasks)
        allocation = _allocate(weights, capacities, trajectory_count)
        selected = _selected_rows(index_rows, allocation, input_sha256)
        tfrecord_handle = archive.extractfile(_member(archive, "rlds/0.1.0/qtail_metaworld-train.tfrecord-00000-of-00001"))
        if tfrecord_handle is None:
            raise RuntimeError("Source TFRecord is unreadable")
        copied_records = _copy_selected_tfrecord(
            tfrecord_handle,
            tfrecord_path,
            {int(row["source_episode_index"]) for row in selected},
            len(index_rows),
        )
        (batch_dir / "METAWORLD_LICENSE.txt").write_bytes(_member_bytes(archive, "METAWORLD_LICENSE.txt"))
        (batch_dir / "robot_contract.json").write_bytes(_member_bytes(archive, "robot_contract.json"))
        (rlds_dir / "features.json").write_bytes(_member_bytes(archive, "rlds/0.1.0/features.json"))
        _write_json(batch_dir / "source_catalog_manifest.json", source_manifest)

    frame_count = sum(int(row["steps"]) for row in selected)
    dataset_info = {
        "name": "qtail_metaworld_sawyer_selected_batch",
        "version": "0.1.0",
        "format": "RLDS-compatible flattened episode TFRecord",
        "episode_count": len(selected),
        "frame_count": frame_count,
        "fps": 20,
        "robot_type": "sawyer_metaworld_mujoco",
        "production_backend": "MuJoCo 3.10.0 / MetaWorld 3.0.0 MT1",
        "tasks": tasks,
        "allocation": allocation,
        "source_catalog_sha256": expected_catalog_sha256,
        "evidence_scope": "simulation",
        "buyer_gate_passed": False,
    }
    _write_json(rlds_dir / "dataset_info.json", dataset_info)
    _write_json(batch_dir / "trajectory_selection.json", selected)
    shutil.copy2(plan_path, batch_dir / "qtail_allocation_plan.csv")
    shutil.copy2(input_path, batch_dir / input_path.name)
    readme = """# Q-Tail simulation trajectory batch

This package contains complete TFRecord episodes selected from the immutable,
SHA-256-verified Q-Tail MetaWorld/Sawyer source catalog. Selection is driven by
the Q-Tail allocation plan included as `qtail_allocation_plan.csv`.

The RLDS-compatible batch is trainable simulator data. It is not a buyer-
selected production backend run, real-robot evidence, an invoice, policy uplift
evidence, procurement acceptance, or an executed contract.
"""
    (batch_dir / "README_QTAIL_TRAJECTORY_BATCH.md").write_text(readme, encoding="utf-8")

    artifact_files = sorted(path for path in batch_dir.rglob("*") if path.is_file())
    manifest = {
        "package_type": "qtail_simulation_trajectory_batch",
        "generated_at": datetime.now(UTC).isoformat(),
        "delivery_product": DELIVERY_PRODUCT,
        "input_sha256": input_sha256,
        "source_catalog_sha256": expected_catalog_sha256,
        "source_catalog_manifest_sha256": expected_manifest_sha256,
        "selection_method": "Q-Tail allocation-plan weighted selection from immutable validated source episodes",
        "requested_trajectory_count": trajectory_count,
        "trajectory_count": copied_records,
        "frame_count": frame_count,
        "trajectory_allocation": allocation,
        "tasks": tasks,
        "formats": ["RLDS-compatible TFRecord"],
        "evidence_scope": "simulation",
        "buyer_gate_passed": False,
        "claim_boundary": [
            "Complete synthetic simulator episodes are included in the delivery.",
            "The source catalog passed RLDS and LeRobot v3 validation before publication.",
            "This request-specific batch is not buyer production-backend, real-robot, cost, safety, or procurement evidence.",
        ],
        "validation": {
            "source_archive_sha256_verified": True,
            "source_manifest_sha256_verified": True,
            "source_record_count": len(index_rows),
            "selected_record_count": copied_records,
            "record_framing_preserved": True,
        },
        "files": [
            {"path": str(path.relative_to(batch_dir)), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
            for path in artifact_files
        ],
    }
    manifest_path = batch_dir / "package_manifest.json"
    _write_json(manifest_path, manifest)
    archive_path = out_dir / "qtail_simulation_trajectory_batch.zip"
    with zipfile.ZipFile(archive_path, "w") as delivery_zip:
        for path in sorted(item for item in batch_dir.rglob("*") if item.is_file()):
            compression = zipfile.ZIP_STORED if "tfrecord" in path.name else zipfile.ZIP_DEFLATED
            delivery_zip.write(path, arcname=str(path.relative_to(batch_dir)), compress_type=compression)
    archive_sha256 = sha256_file(archive_path)
    return {
        "package_zip": str(archive_path),
        "package_manifest": str(manifest_path),
        "trajectory_manifest": str(batch_dir / "trajectory_selection.json"),
        "synthetic_plan": str(batch_dir / "qtail_allocation_plan.csv"),
        "readme": str(batch_dir / "README_QTAIL_TRAJECTORY_BATCH.md"),
        "model_card": allocation_delivery.get("model_card"),
        "delivery_report": allocation_delivery.get("delivery_report"),
        "effect_summary": {
            "package_type": manifest["package_type"],
            "trajectory_count": copied_records,
            "frame_count": frame_count,
            "archive_sha256": archive_sha256,
            "source_catalog_sha256": expected_catalog_sha256,
            "evidence_scope": "simulation",
            "buyer_gate_passed": False,
        },
    }
