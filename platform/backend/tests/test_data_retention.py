from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import unittest
import uuid
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("ADMIN_TOKEN", "integration-admin-token-at-least-32-characters")
os.environ.setdefault("APP_SECRET", "integration-app-secret-at-least-32-characters")
os.environ.setdefault("QTAIL_FAKE_GENERATOR", "1")

from app import JOBS_DIR, create_app  # noqa: E402
from db import execute, fetch_one  # noqa: E402
from worker import process_retention_cycle  # noqa: E402


class DataRetentionLifecycleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app(initialize=True)
        cls.app.config.update(TESTING=True)

    def _completed_job(self, client, suffix: str, *, expired: bool = False) -> tuple[str, str, Path]:
        registered = client.post("/api/auth/register", json={
            "name": "Retention Buyer",
            "company": "Retention Robotics",
            "email": f"retention-{suffix}@example.com",
            "password": "retention-password-2026",
        })
        self.assertEqual(registered.status_code, 201, registered.get_data(as_text=True))
        user_id = registered.get_json()["user"]["id"]
        job_id = str(uuid.uuid4())
        job_dir = JOBS_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=False)
        input_path = job_dir / "customer_tasks.csv"
        output_path = job_dir / "delivery.zip"
        input_bytes = b"task,count\nrare_pick,12\n"
        input_path.write_bytes(input_bytes)
        output_path.write_bytes(b"PK\x03\x04qtail-retention-fixture")
        execute(
            "INSERT INTO generation_jobs (id,user_id,filename,robot_model,control_frequency_hz,sensors,training_format,production_backend,synthetic_budget,status,gate_evaluation,input_sha256,input_path,output_json,output_path,completed_at) "
            "VALUES (%s,%s,'customer_tasks.csv','Franka Panda',20,'RGB-D + joint state','LeRobot v3','MuJoCo',1000,'completed',%s,%s,%s,%s,%s,UTC_TIMESTAMP())",
            (
                job_id,
                user_id,
                json.dumps({"gate0": {"status": "passed"}}),
                hashlib.sha256(input_bytes).hexdigest(),
                str(input_path),
                json.dumps({"package_zip": str(output_path)}),
                str(output_path),
            ),
        )
        execute(
            "INSERT INTO generation_data_rights (generation_job_id,user_id,source_type,license_basis,contains_personal_data,retention_days,source_rights_confirmed,derivative_rights_confirmed,restricted_data_excluded,attestation_version,attestation_sha256,accepted_at) "
            "VALUES (%s,%s,'customer_owned','Retention lifecycle test fixture',FALSE,30,TRUE,TRUE,TRUE,'2026-07-15-v1',%s,UTC_TIMESTAMP())",
            (job_id, user_id, hashlib.sha256(f"rights:{job_id}".encode()).hexdigest()),
        )
        if expired:
            execute(
                "UPDATE generation_data_rights SET accepted_at=UTC_TIMESTAMP()-INTERVAL 31 DAY WHERE generation_job_id=%s",
                (job_id,),
            )
        return user_id, job_id, job_dir

    def test_buyer_request_operator_completion_and_tombstone(self):
        client = self.app.test_client()
        suffix = f"buyer-{int(time.time() * 1000)}-{os.getpid()}"
        _user_id, job_id, job_dir = self._completed_job(client, suffix)
        admin = {"X-Admin-Token": os.environ["ADMIN_TOKEN"]}

        before = client.get(f"/downloads/{job_id}")
        self.assertEqual(before.status_code, 200, before.get_data(as_text=True))
        before.close()
        short = client.post(f"/api/generations/{job_id}/deletion-request", json={"reason": "删除"})
        self.assertEqual(short.status_code, 400, short.get_data(as_text=True))

        created = client.post(
            f"/api/generations/{job_id}/deletion-request",
            json={"reason": "客户试点结束，删除输入与交付载荷。"},
        )
        self.assertEqual(created.status_code, 201, created.get_data(as_text=True))
        deletion = created.get_json()["deletion_request"]
        self.assertEqual(deletion["status"], "requested")
        reused = client.post(
            f"/api/generations/{job_id}/deletion-request",
            json={"reason": "重复申请不应创建第二条记录。"},
        )
        self.assertEqual(reused.status_code, 200, reused.get_data(as_text=True))
        self.assertTrue(reused.get_json()["reused"])

        queue = client.get("/api/admin/summary", headers=admin).get_json()["deletion_requests"]
        self.assertIn(deletion["id"], [item["id"] for item in queue])
        completed = client.post(
            f"/api/admin/data-deletion-requests/{deletion['id']}/complete",
            headers=admin,
            json={"review_note": "Retention fixture scope verified and deleted."},
        )
        self.assertEqual(completed.status_code, 200, completed.get_data(as_text=True))
        receipt = completed.get_json()["deletion_request"]
        self.assertEqual(receipt["status"], "completed")
        self.assertEqual(len(receipt["deletion_sha256"]), 64)
        self.assertGreaterEqual(receipt["files_deleted"], 2)
        self.assertFalse(job_dir.exists())

        gone = client.get(f"/downloads/{job_id}")
        self.assertEqual(gone.status_code, 410, gone.get_data(as_text=True))
        self.assertEqual(gone.get_json()["error"]["code"], "payload_deleted")
        job = client.get(f"/api/generations/{job_id}").get_json()
        self.assertTrue(job["payload_deleted"])
        self.assertIsNone(job["download_url"])
        self.assertIsNone(fetch_one("SELECT output_path FROM generation_jobs WHERE id=%s", (job_id,))["output_path"])
        exported = client.get("/api/account/export").get_json()
        self.assertIn(deletion["id"], [item["id"] for item in exported["data_deletion_requests"]])

        idempotent = client.post(
            f"/api/admin/data-deletion-requests/{deletion['id']}/complete",
            headers=admin,
            json={},
        )
        self.assertEqual(idempotent.status_code, 200, idempotent.get_data(as_text=True))
        self.assertTrue(idempotent.get_json()["reused"])

    def test_retention_worker_respects_pause_then_purges_expired_payload(self):
        client = self.app.test_client()
        suffix = f"worker-{int(time.time() * 1000)}-{os.getpid()}"
        _user_id, job_id, job_dir = self._completed_job(client, suffix, expired=True)
        execute(
            "INSERT INTO system_settings (setting_key,setting_value) VALUES ('worker_paused','1') ON DUPLICATE KEY UPDATE setting_value='1'"
        )
        try:
            paused = process_retention_cycle()
            self.assertEqual(paused, {"enqueued": 0, "completed": 0, "failed": 0})
            self.assertTrue(job_dir.exists())
        finally:
            execute("UPDATE system_settings SET setting_value='0' WHERE setting_key='worker_paused'")

        result = process_retention_cycle()
        self.assertGreaterEqual(result["enqueued"], 1)
        self.assertGreaterEqual(result["completed"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertFalse(job_dir.exists())
        deletion = fetch_one("SELECT * FROM data_deletion_requests WHERE generation_job_id=%s", (job_id,))
        self.assertEqual(deletion["request_source"], "retention")
        self.assertEqual(deletion["status"], "completed")
        self.assertEqual(len(deletion["deletion_sha256"]), 64)


if __name__ == "__main__":
    unittest.main(verbosity=2)
