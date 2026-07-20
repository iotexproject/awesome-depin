from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("ADMIN_TOKEN", "integration-admin-token-at-least-32-characters")
os.environ.setdefault("APP_SECRET", "integration-app-secret-at-least-32-characters")
os.environ.setdefault("QTAIL_FAKE_GENERATOR", "1")

from app import JOBS_DIR, create_app  # noqa: E402
from db import execute, fetch_one  # noqa: E402
from security import password_hash  # noqa: E402
from worker import process_one, recover_expired_jobs  # noqa: E402


CSV_TEXT = "task,count,success_rate,difficulty,group\nrare_pick,12,0.32,0.91,tail\n"


class DurableWorkerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app(initialize=True)

    def setUp(self):
        self.user_id = str(uuid.uuid4())
        self.job_ids: list[str] = []
        execute(
            "INSERT INTO users (id,email,password_hash,name,company) VALUES (%s,%s,%s,'Worker Test','Q-Tail QA')",
            (self.user_id, f"worker-{time.time_ns()}@example.com", password_hash("worker-test-password-2026")),
        )

    def tearDown(self):
        execute("INSERT INTO system_settings (setting_key,setting_value) VALUES ('worker_paused','0') ON DUPLICATE KEY UPDATE setting_value='0'")
        execute("DELETE FROM users WHERE id=%s", (self.user_id,))
        for job_id in self.job_ids:
            shutil.rmtree(JOBS_DIR / job_id, ignore_errors=True)

    def create_job(self, *, status: str = "queued", max_attempts: int = 3, expired_lease: bool = False) -> str:
        job_id = str(uuid.uuid4())
        self.job_ids.append(job_id)
        job_dir = JOBS_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        input_path = job_dir / "worker_tasks.csv"
        input_path.write_text(CSV_TEXT, encoding="utf-8")
        execute(
            "INSERT INTO generation_jobs (id,user_id,filename,robot_model,control_frequency_hz,sensors,training_format,production_backend,synthetic_budget,status,gate_evaluation,input_sha256,input_path,max_attempts,attempt_count,worker_id,lease_expires_at,started_at) "
            "VALUES (%s,%s,'worker_tasks.csv','Franka Panda',20,'RGB-D','LeRobot v3','MuJoCo',1000,%s,%s,%s,%s,%s,%s,%s,"
            + ("UTC_TIMESTAMP()-INTERVAL 10 SECOND,UTC_TIMESTAMP())" if expired_lease else "NULL,NULL)"),
            (
                job_id,
                self.user_id,
                status,
                json.dumps({"request_allowed": True}),
                hashlib.sha256(CSV_TEXT.encode()).hexdigest(),
                str(input_path.resolve()),
                max_attempts,
                1 if status == "running" else 0,
                "dead-worker" if status == "running" else None,
            ),
        )
        return job_id

    def test_max_attempt_failure_is_durable_and_audited(self):
        job_id = self.create_job(max_attempts=1)
        with patch("worker.generate_package", side_effect=RuntimeError("synthetic backend unavailable")):
            result = process_one("unit-worker-failure", job_id)
        self.assertEqual(result["status"], "failed", result)
        job = fetch_one("SELECT status,attempt_count,error_message,completed_at FROM generation_jobs WHERE id=%s", (job_id,))
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["attempt_count"], 1)
        self.assertIn("backend unavailable", job["error_message"])
        self.assertIsNotNone(job["completed_at"])
        event = fetch_one("SELECT event_type FROM audit_events WHERE object_type='generation_job' AND object_id=%s ORDER BY id DESC LIMIT 1", (job_id,))
        self.assertEqual(event["event_type"], "generation.failed")

    def test_expired_worker_lease_is_requeued(self):
        job_id = self.create_job(status="running", expired_lease=True)
        result = recover_expired_jobs()
        self.assertGreaterEqual(result["recovered"], 1)
        job = fetch_one("SELECT status,worker_id,lease_expires_at,error_message FROM generation_jobs WHERE id=%s", (job_id,))
        self.assertEqual(job["status"], "queued")
        self.assertIsNone(job["worker_id"])
        self.assertIsNone(job["lease_expires_at"])
        self.assertIn("requeued", job["error_message"])

    def test_backup_pause_prevents_new_claims(self):
        job_id = self.create_job()
        execute("INSERT INTO system_settings (setting_key,setting_value) VALUES ('worker_paused','1') ON DUPLICATE KEY UPDATE setting_value='1'")
        self.assertIsNone(process_one("unit-worker-paused", job_id))
        self.assertEqual(fetch_one("SELECT status FROM generation_jobs WHERE id=%s", (job_id,))["status"], "queued")

    def test_concurrent_submission_enforces_atomic_active_queue_limit(self):
        execute("UPDATE users SET plan='pro',pro_expires_at=UTC_TIMESTAMP()+INTERVAL 1 DAY WHERE id=%s", (self.user_id,))

        def submit(index: int) -> tuple[int, dict]:
            client = self.app.test_client()
            logged_in = client.post("/api/auth/login", json={"email": fetch_one("SELECT email FROM users WHERE id=%s", (self.user_id,))["email"], "password": "worker-test-password-2026"})
            self.assertEqual(logged_in.status_code, 200, logged_in.get_data(as_text=True))
            response = client.post("/api/generations", json={
                "robot_model": "Franka Panda", "control_frequency_hz": 20, "sensors": "RGB-D",
                "training_format": "LeRobot v3", "production_backend": "Queue concurrency test",
                "synthetic_budget": 1000, "filename": f"concurrent_{index}.csv", "csv_text": CSV_TEXT,
                "claim_acknowledged": True,
                "data_rights": {
                    "source_type": "customer_owned", "license_basis": "Worker concurrency test fixture",
                    "contains_personal_data": False, "retention_days": 30,
                    "source_rights_confirmed": True, "derivative_rights_confirmed": True,
                    "restricted_data_excluded": True,
                },
            })
            return response.status_code, response.get_json()

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(submit, range(8)))
        accepted = [body for status, body in results if status == 202]
        rejected = [body for status, body in results if status == 429]
        self.assertEqual(len(accepted), 5, results)
        self.assertEqual(len(rejected), 3, results)
        self.assertTrue(all(item["error"]["code"] == "active_queue_limit_exceeded" for item in rejected))
        self.assertEqual(fetch_one("SELECT generation_count FROM api_usage_daily WHERE user_id=%s AND usage_date=UTC_DATE()", (self.user_id,))["generation_count"], 5)
        self.job_ids.extend(item["job_id"] for item in accepted)


if __name__ == "__main__":
    unittest.main(verbosity=2)
