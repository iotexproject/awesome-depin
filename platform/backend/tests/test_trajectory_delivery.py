from __future__ import annotations

import hashlib
import json
import struct
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from trajectory_delivery import build_trajectory_batch, validate_trajectory_request  # noqa: E402


def tfrecord_record(payload: bytes) -> bytes:
    return struct.pack("<Q", len(payload)) + b"LCRC" + payload + b"DCRC"


class TrajectoryDeliveryTest(unittest.TestCase):
    def test_request_contract_rejects_unsupported_task_and_accepts_locked_source(self):
        base = {
            "trajectory_count": 3,
            "robot_model": "Sawyer / MetaWorld",
            "control_frequency_hz": 20,
            "sensors": "256x256 RGB + 39D state",
            "training_format": "RLDS",
            "production_backend": "MuJoCo / MetaWorld",
            "csv_text": "task,count\nreach-v3,2\npick-place-v3,1\n",
        }
        self.assertEqual(validate_trajectory_request(base)["trajectory_count"], 3)
        with self.assertRaisesRegex(ValueError, "不支持任务"):
            validate_trajectory_request({**base, "csv_text": "task,count\nunsupported-v0,3\n"})
        with self.assertRaisesRegex(ValueError, "20 Hz"):
            validate_trajectory_request({**base, "control_frequency_hz": 50})

    def test_materializes_complete_selected_records_and_auditable_boundary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            prefix = source / "catalog"
            rlds = prefix / "rlds" / "0.1.0"
            rlds.mkdir(parents=True)
            index = [
                {"episode_index": 0, "task": "reach-v3", "steps": 3},
                {"episode_index": 1, "task": "reach-v3", "steps": 4},
                {"episode_index": 2, "task": "pick-place-v3", "steps": 5},
            ]
            manifest_bytes = b'{"package":"mini-source"}\n'
            (prefix / "package_manifest.json").write_bytes(manifest_bytes)
            (prefix / "trajectory_index.json").write_text(json.dumps(index), encoding="utf-8")
            (prefix / "robot_contract.json").write_text('{"robot":"Sawyer"}', encoding="utf-8")
            (prefix / "METAWORLD_LICENSE.txt").write_text("test license", encoding="utf-8")
            (rlds / "features.json").write_text('{"feature":"bytes"}', encoding="utf-8")
            records = [tfrecord_record(f"episode-{number}".encode()) for number in range(3)]
            (rlds / "qtail_metaworld-train.tfrecord-00000-of-00001").write_bytes(b"".join(records))
            archive_path = root / "catalog.tar.gz"
            with tarfile.open(archive_path, "w:gz") as archive:
                archive.add(prefix, arcname="catalog")

            input_path = root / "tasks.csv"
            input_path.write_text("task,count\nreach-v3,2\npick-place-v3,1\n", encoding="utf-8")
            plan_path = root / "plan.csv"
            plan_path.write_text("task_id,synthetic_count\nreach-v3,2\npick-place-v3,1\n", encoding="utf-8")
            output = root / "delivery"
            output.mkdir()
            delivery = build_trajectory_batch(
                input_path=input_path,
                out_dir=output,
                allocation_delivery={"synthetic_plan": str(plan_path)},
                trajectory_count=3,
                catalog_path=archive_path,
                expected_catalog_bytes=archive_path.stat().st_size,
                expected_catalog_sha256=hashlib.sha256(archive_path.read_bytes()).hexdigest(),
                expected_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
            )
            package_manifest = json.loads(Path(delivery["package_manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(package_manifest["trajectory_count"], 3)
            self.assertEqual(package_manifest["frame_count"], 12)
            self.assertEqual(package_manifest["evidence_scope"], "simulation")
            self.assertFalse(package_manifest["buyer_gate_passed"])
            with zipfile.ZipFile(delivery["package_zip"]) as archive:
                names = archive.namelist()
                tfrecord_name = next(name for name in names if "tfrecord" in name)
                self.assertEqual(archive.read(tfrecord_name), b"".join(records))
                embedded = json.loads(archive.read("package_manifest.json"))
                self.assertTrue(embedded["validation"]["record_framing_preserved"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
