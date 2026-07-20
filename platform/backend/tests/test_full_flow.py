from __future__ import annotations

import json
import hashlib
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("ADMIN_TOKEN", "integration-admin-token-at-least-32-characters")
os.environ.setdefault("APP_SECRET", "integration-app-secret-at-least-32-characters")
os.environ.setdefault("QTAIL_FAKE_GENERATOR", "1")

import app as app_module  # noqa: E402
from app import create_app  # noqa: E402
from worker import process_one  # noqa: E402


GENERATION_PAYLOAD = {
    "robot_model": "Franka Panda",
    "control_frequency_hz": 20,
    "sensors": "RGB-D + joint state",
    "training_format": "LeRobot v3",
    "production_backend": "MuJoCo",
    "synthetic_budget": 100000,
    "filename": "integration_tasks.csv",
    "csv_text": "task,count,success_rate,difficulty,group\nrare_pick,12,0.32,0.91,tail\nstandard_pick,540,0.86,0.22,head\n",
    "claim_acknowledged": True,
    "data_rights": {
        "source_type": "customer_owned",
        "license_basis": "Integration fixture owned by test buyer",
        "contains_personal_data": False,
        "retention_days": 30,
        "source_rights_confirmed": True,
        "derivative_rights_confirmed": True,
        "restricted_data_excluded": True,
    },
}


class FullCommercialFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app(initialize=True)
        cls.app.config.update(TESTING=True)

    def test_register_approve_pay_key_generate_download(self):
        client = self.app.test_client()
        suffix = f"{int(time.time() * 1000)}-{os.getpid()}"
        email = f"buyer-{suffix}@example.com"

        health = client.get("/api/health")
        self.assertEqual(health.status_code, 200, health.get_data(as_text=True))
        self.assertEqual(health.get_json()["database"], "mysql")

        registered = client.post(
            "/api/auth/register",
            json={"name": "Integration Buyer", "company": "Q-Tail Test Lab", "email": email, "password": "buyer-password-2026"},
        )
        self.assertEqual(registered.status_code, 201, registered.get_data(as_text=True))
        self.assertFalse(registered.get_json()["user"]["is_pro"])

        blocked_generation = client.post("/api/generations", json=GENERATION_PAYLOAD)
        self.assertEqual(blocked_generation.status_code, 402, blocked_generation.get_data(as_text=True))
        blocked_catalog = client.get("/api/catalogs")
        self.assertEqual(blocked_catalog.status_code, 402, blocked_catalog.get_data(as_text=True))

        application = client.post(
            "/api/api-access",
            json={
                "role": "机器人数据负责人",
                "use_case": "工业机械臂长尾任务预算编排",
                "data_format": "CSV / LeRobot v3",
                "monthly_volume": "100,000 units",
                "pilot_goal": "围绕尾部任务完成可审计 PoC。",
            },
        )
        self.assertEqual(application.status_code, 201, application.get_data(as_text=True))
        application_id = application.get_json()["application"]["id"]

        operator_queue = client.get("/api/admin/summary", headers={"X-Admin-Token": os.environ["ADMIN_TOKEN"]})
        self.assertEqual(operator_queue.status_code, 200, operator_queue.get_data(as_text=True))
        self.assertIn(application_id, [item["id"] for item in operator_queue.get_json()["applications"]])

        approved = client.post(
            f"/api/admin/api-access/{application_id}/approve",
            headers={"X-Admin-Token": os.environ["ADMIN_TOKEN"]},
            json={"review_note": "Integration approval"},
        )
        self.assertEqual(approved.status_code, 200, approved.get_data(as_text=True))

        early_key = client.post("/api/api-keys", json={"label": "Too early"})
        self.assertEqual(early_key.status_code, 402, early_key.get_data(as_text=True))

        order = client.post("/api/payment-orders", json={"channel": "wechat"})
        self.assertEqual(order.status_code, 201, order.get_data(as_text=True))
        order_id = order.get_json()["order"]["id"]

        submitted = client.post(
            f"/api/payment-orders/{order_id}/submit",
            json={"payment_reference": f"TEST-{suffix}"},
        )
        self.assertEqual(submitted.status_code, 200, submitted.get_data(as_text=True))
        self.assertEqual(submitted.get_json()["order"]["status"], "under_review")

        payment_queue = client.get("/api/admin/summary", headers={"X-Admin-Token": os.environ["ADMIN_TOKEN"]})
        self.assertIn(order_id, [item["id"] for item in payment_queue.get_json()["payments"]])

        confirmed = client.post(
            f"/api/admin/payment-orders/{order_id}/confirm",
            headers={"X-Admin-Token": os.environ["ADMIN_TOKEN"]},
            json={"review_note": "Integration payment verification"},
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.get_data(as_text=True))
        self.assertEqual(confirmed.get_json()["order"]["status"], "paid")

        me = client.get("/api/auth/me")
        self.assertEqual(me.status_code, 200, me.get_data(as_text=True))
        self.assertTrue(me.get_json()["user"]["is_pro"])

        key_response = client.post("/api/api-keys", json={"label": "Integration key"})
        self.assertEqual(key_response.status_code, 201, key_response.get_data(as_text=True))
        raw_key = key_response.get_json()["api_key"]
        self.assertTrue(raw_key.startswith("qtail_live_"))

        api_client = self.app.test_client()
        anonymous_catalog = api_client.get("/api/catalogs")
        self.assertEqual(anonymous_catalog.status_code, 401, anonymous_catalog.get_data(as_text=True))
        with tempfile.TemporaryDirectory() as catalog_dir:
            payload = b"qtail-synthetic-catalog-fixture-v1\n"
            filename = "fixture.tar.gz"
            Path(catalog_dir, filename).write_bytes(payload)
            fixture_catalog = {
                "slug": "fixture-v1", "title": "Fixture", "filename": filename,
                "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
                "dataset_manifest_sha256": "1" * 64, "embodiment": "test",
                "formats": ["LeRobotDataset v3"], "tasks": ["fixture"],
                "trajectory_count": 1, "frame_count": 1, "evidence_scope": "simulation",
                "buyer_gate_passed": False, "claim_boundary": "Test fixture; not buyer evidence.",
            }
            app_module._catalog_file_sha256.cache_clear()
            with patch.object(app_module, "CATALOG_DIR", Path(catalog_dir).resolve()), patch.object(app_module, "SYNTHETIC_CATALOGS", (fixture_catalog,)):
                catalog_list = api_client.get("/api/catalogs", headers={"X-API-Key": raw_key})
                self.assertEqual(catalog_list.status_code, 200, catalog_list.get_data(as_text=True))
                catalog_json = catalog_list.get_json()["catalogs"][0]
                self.assertTrue(catalog_json["available"])
                self.assertFalse(catalog_json["buyer_gate_passed"])
                package_response = api_client.get(catalog_json["download_url"], headers={"X-API-Key": raw_key})
                self.assertEqual(package_response.status_code, 200, package_response.get_data(as_text=True))
                self.assertEqual(package_response.data, payload)
                self.assertEqual(package_response.headers["X-Content-SHA256"], fixture_catalog["sha256"])
                self.assertEqual(package_response.headers["X-QTail-Evidence-Scope"], "simulation")
                package_response.close()
            app_module._catalog_file_sha256.cache_clear()

        missing_rights_payload = dict(GENERATION_PAYLOAD)
        missing_rights_payload.pop("data_rights")
        missing_rights = api_client.post("/api/generations", headers={"X-API-Key": raw_key}, json=missing_rights_payload)
        self.assertEqual(missing_rights.status_code, 422, missing_rights.get_data(as_text=True))
        self.assertEqual(missing_rights.get_json()["error"]["code"], "data_rights_attestation_required")
        generated = api_client.post(
            "/api/generations",
            headers={"X-API-Key": raw_key},
            json=GENERATION_PAYLOAD,
        )
        self.assertEqual(generated.status_code, 202, generated.get_data(as_text=True))
        generated_json = generated.get_json()
        self.assertEqual(generated_json["status"], "queued")
        self.assertEqual(generated_json["gate_evaluation"]["gate0"]["status"], "passed")
        self.assertEqual(generated_json["gate_evaluation"]["gate2"]["status"], "not_validated")
        self.assertEqual(len(generated_json["data_rights"]["attestation_sha256"]), 64)
        worker_result = process_one(f"unit-full-flow-{suffix}", generated_json["job_id"])
        self.assertEqual(worker_result["status"], "completed", worker_result)
        completed = api_client.get(generated_json["status_url"], headers={"X-API-Key": raw_key})
        self.assertEqual(completed.status_code, 200, completed.get_data(as_text=True))
        generated_json = completed.get_json()
        self.assertEqual(generated_json["status"], "completed")

        package = api_client.get(generated_json["download_url"], headers={"X-API-Key": raw_key})
        self.assertEqual(package.status_code, 200)
        self.assertTrue(package.data.startswith(b"PK"))
        package.close()

        anonymous_status = self.app.test_client().get(generated_json["status_url"])
        self.assertEqual(anonymous_status.status_code, 401, anonymous_status.get_data(as_text=True))
        other = self.app.test_client()
        self.assertEqual(other.post("/api/auth/register", json={
            "name": "Other Queue Buyer", "company": "Other Robotics",
            "email": f"other-queue-{suffix}@example.com", "password": "other-queue-password-2026",
        }).status_code, 201)
        isolated = other.get(generated_json["status_url"])
        self.assertEqual(isolated.status_code, 404, isolated.get_data(as_text=True))

        ledger = api_client.get("/api/generations", headers={"X-API-Key": raw_key})
        self.assertEqual(ledger.status_code, 200, ledger.get_data(as_text=True))
        self.assertGreaterEqual(len(ledger.get_json()["jobs"]), 1)

        print(
            json.dumps(
                {
                    "email": email,
                    "application_id": application_id,
                    "order_id": order_id,
                    "job_id": generated_json["job_id"],
                    "result": "passed",
                },
                ensure_ascii=False,
            )
        )

    def test_protected_operations_health(self):
        client = self.app.test_client()
        denied = client.get("/api/admin/health")
        self.assertEqual(denied.status_code, 403, denied.get_data(as_text=True))

        response = client.get(
            "/api/admin/health",
            headers={"X-Admin-Token": os.environ["ADMIN_TOKEN"]},
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["database"], "mysql")
        self.assertIn("jobs_queued", payload["metrics"])
        self.assertIn("jobs_failed_24h", payload["metrics"])
        self.assertIn("worker_paused", payload["metrics"])
        self.assertIn("bytes", payload["delivery_storage"])

    def test_invoice_and_refund_audit_workflow(self):
        client = self.app.test_client()
        suffix = f"{int(time.time() * 1000)}-{os.getpid()}"
        admin = {"X-Admin-Token": os.environ["ADMIN_TOKEN"]}
        registered = client.post("/api/auth/register", json={
            "name": "Billing Buyer",
            "company": "Billing Robotics",
            "email": f"billing-{suffix}@example.com",
            "password": "billing-password-2026",
        })
        self.assertEqual(registered.status_code, 201, registered.get_data(as_text=True))

        order = client.post("/api/payment-orders", json={"channel": "alipay"}).get_json()["order"]
        self.assertEqual(client.post(f"/api/payment-orders/{order['id']}/submit", json={"payment_reference": f"BILL-{suffix}"}).status_code, 200)
        self.assertEqual(client.post(f"/api/admin/payment-orders/{order['id']}/confirm", headers=admin, json={}).status_code, 200)
        self.assertTrue(client.get("/api/auth/me").get_json()["user"]["is_pro"])
        application = client.post("/api/api-access", json={
            "role": "财务与数据负责人", "use_case": "退款撤权验证", "data_format": "CSV",
            "monthly_volume": "1,000 units", "pilot_goal": "验证退款完成后 API 凭据撤销。",
        }).get_json()["application"]
        self.assertEqual(client.post(f"/api/admin/api-access/{application['id']}/approve", headers=admin, json={}).status_code, 200)
        raw_key = client.post("/api/api-keys", json={"label": "Refund revocation key"}).get_json()["api_key"]

        invalid_invoice = client.post(f"/api/payment-orders/{order['id']}/invoice-requests", json={
            "invoice_title": "Billing Robotics",
            "taxpayer_id": "bad",
            "invoice_email": "billing@example.com",
        })
        self.assertEqual(invalid_invoice.status_code, 400, invalid_invoice.get_data(as_text=True))
        invoice = client.post(f"/api/payment-orders/{order['id']}/invoice-requests", json={
            "invoice_title": "Billing Robotics Co., Ltd.",
            "taxpayer_id": "91110108MA01234567",
            "invoice_email": "billing@example.com",
        })
        self.assertEqual(invoice.status_code, 201, invoice.get_data(as_text=True))
        invoice_id = invoice.get_json()["invoice_request"]["id"]
        queue = client.get("/api/admin/summary", headers=admin).get_json()
        self.assertIn(invoice_id, [item["id"] for item in queue["invoice_requests"]])

        issued = client.post(f"/api/admin/invoice-requests/{invoice_id}/issue", headers=admin, json={
            "invoice_number": f"QA-INVOICE-{suffix}",
            "invoice_document_url": "https://evidence.example/invoice.pdf",
        })
        self.assertEqual(issued.status_code, 200, issued.get_data(as_text=True))
        self.assertEqual(issued.get_json()["invoice_request"]["status"], "issued")

        short_refund = client.post(f"/api/payment-orders/{order['id']}/refund-requests", json={"reason": "短"})
        self.assertEqual(short_refund.status_code, 400, short_refund.get_data(as_text=True))
        refund = client.post(f"/api/payment-orders/{order['id']}/refund-requests", json={"reason": "设计伙伴测试结束，申请原路全额退款。"})
        self.assertEqual(refund.status_code, 201, refund.get_data(as_text=True))
        refund_id = refund.get_json()["refund_request"]["id"]
        approved = client.post(f"/api/admin/refund-requests/{refund_id}/approve", headers=admin, json={})
        self.assertEqual(approved.status_code, 200, approved.get_data(as_text=True))
        self.assertTrue(client.get("/api/auth/me").get_json()["user"]["is_pro"])

        blocked = client.post(f"/api/admin/refund-requests/{refund_id}/complete", headers=admin, json={"refund_reference": f"QA-REFUND-{suffix}"})
        self.assertEqual(blocked.status_code, 409, blocked.get_data(as_text=True))
        self.assertEqual(blocked.get_json()["error"]["code"], "invoice_cancellation_required")
        cancelled = client.post(f"/api/admin/invoice-requests/{invoice_id}/cancel", headers=admin, json={"cancellation_reference": f"QA-RED-{suffix}"})
        self.assertEqual(cancelled.status_code, 200, cancelled.get_data(as_text=True))
        completed = client.post(f"/api/admin/refund-requests/{refund_id}/complete", headers=admin, json={"refund_reference": f"QA-REFUND-{suffix}"})
        self.assertEqual(completed.status_code, 200, completed.get_data(as_text=True))
        self.assertEqual(completed.get_json()["refund_request"]["status"], "completed")

        billing = client.get("/api/billing").get_json()
        self.assertEqual(next(item for item in billing["orders"] if item["id"] == order["id"])["status"], "refunded")
        self.assertEqual(next(item for item in billing["invoice_requests"] if item["id"] == invoice_id)["status"], "cancelled")
        self.assertEqual(next(item for item in billing["refund_requests"] if item["id"] == refund_id)["status"], "completed")
        self.assertFalse(client.get("/api/auth/me").get_json()["user"]["is_pro"])
        keys = client.get("/api/api-access").get_json()["keys"]
        self.assertEqual(keys[0]["status"], "revoked")
        denied_key = self.app.test_client().get("/api/generations", headers={"X-API-Key": raw_key})
        self.assertEqual(denied_key.status_code, 401, denied_key.get_data(as_text=True))

    def test_account_export_and_closure(self):
        client = self.app.test_client()
        suffix = f"{int(time.time() * 1000)}-{os.getpid()}"
        email = f"privacy-{suffix}@example.com"
        password = "privacy-test-password-2026"
        registered = client.post("/api/auth/register", json={
            "name": "Privacy Test",
            "company": "Q-Tail Test Lab",
            "email": email,
            "password": password,
        })
        self.assertEqual(registered.status_code, 201, registered.get_data(as_text=True))

        exported = client.get("/api/account/export")
        self.assertEqual(exported.status_code, 200, exported.get_data(as_text=True))
        self.assertEqual(exported.get_json()["account"]["email"], email)
        self.assertNotIn("password_hash", exported.get_data(as_text=True))

        invalid = client.delete("/api/account", json={"password": password, "confirmation": "DELETE"})
        self.assertEqual(invalid.status_code, 400, invalid.get_data(as_text=True))
        closed = client.delete("/api/account", json={"password": password, "confirmation": "CLOSE MY ACCOUNT"})
        self.assertEqual(closed.status_code, 200, closed.get_data(as_text=True))
        self.assertEqual(closed.get_json()["status"], "closed")
        self.assertEqual(client.get("/api/auth/me").status_code, 401)
        self.assertEqual(client.post("/api/auth/login", json={"email": email, "password": password}).status_code, 401)


if __name__ == "__main__":
    unittest.main(verbosity=2)
