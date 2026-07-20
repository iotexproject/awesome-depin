from __future__ import annotations

import os
import shutil
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

from app import JOBS_DIR, create_app  # noqa: E402
from db import execute, fetch_one  # noqa: E402
from security import password_hash  # noqa: E402


class TrajectoryApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app(initialize=True)

    def setUp(self):
        self.user_id = str(uuid.uuid4())
        self.email = f"trajectory-{time.time_ns()}@example.com"
        self.password = "trajectory-test-password-2026"
        self.job_ids: list[str] = []
        execute(
            "INSERT INTO users (id,email,password_hash,name,company,plan,pro_expires_at) "
            "VALUES (%s,%s,%s,'Trajectory Test','Q-Tail QA','pro',UTC_TIMESTAMP()+INTERVAL 1 DAY)",
            (self.user_id, self.email, password_hash(self.password)),
        )
        self.client = self.app.test_client()
        response = self.client.post("/api/auth/login", json={"email": self.email, "password": self.password})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))

    def tearDown(self):
        execute("DELETE FROM users WHERE id=%s", (self.user_id,))
        for job_id in self.job_ids:
            shutil.rmtree(JOBS_DIR / job_id, ignore_errors=True)

    def payload(self) -> dict:
        return {
            "delivery_product": "simulation_trajectory_batch",
            "trajectory_count": 8,
            "robot_model": "Sawyer / MetaWorld",
            "control_frequency_hz": 20,
            "sensors": "256x256 RGB + 39D state",
            "training_format": "RLDS",
            "production_backend": "MuJoCo / MetaWorld",
            "synthetic_budget": 1000,
            "filename": "metaworld_tasks.csv",
            "csv_text": "task,count\nreach-v3,50\nbutton-press-v3,7\npick-place-v3,7\n",
            "claim_acknowledged": True,
            "data_rights": {
                "source_type": "customer_owned",
                "license_basis": "Customer-owned task selection",
                "contains_personal_data": False,
                "retention_days": 30,
                "source_rights_confirmed": True,
                "derivative_rights_confirmed": True,
                "restricted_data_excluded": True,
            },
        }

    def test_valid_trajectory_job_is_persisted_with_simulation_boundary(self):
        response = self.client.post("/api/generations", json=self.payload())
        self.assertEqual(response.status_code, 202, response.get_data(as_text=True))
        body = response.get_json()
        self.job_ids.append(body["job_id"])
        self.assertEqual(body["delivery_product"], "simulation_trajectory_batch")
        self.assertEqual(body["trajectory_count"], 8)
        self.assertEqual(body["gate_evaluation"]["gate1"]["evidence"]["evidence_scope"], "simulation")
        self.assertFalse(body["gate_evaluation"]["gate1"]["evidence"]["buyer_gate_passed"])
        row = fetch_one("SELECT delivery_product,trajectory_count FROM generation_jobs WHERE id=%s", (body["job_id"],))
        self.assertEqual(row["delivery_product"], "simulation_trajectory_batch")
        self.assertEqual(int(row["trajectory_count"]), 8)

    def test_unsupported_task_is_rejected_before_queueing(self):
        payload = self.payload()
        payload["csv_text"] = "task,count\nunknown-v0,1\n"
        response = self.client.post("/api/generations", json=payload)
        self.assertEqual(response.status_code, 422, response.get_data(as_text=True))
        self.assertEqual(response.get_json()["error"]["code"], "trajectory_contract_invalid")
        self.assertEqual(fetch_one("SELECT COUNT(*) AS count FROM generation_jobs WHERE user_id=%s", (self.user_id,))["count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
