from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("ADMIN_TOKEN", "integration-admin-token-at-least-32-characters")
os.environ.setdefault("APP_SECRET", "integration-app-secret-at-least-32-characters")
os.environ.setdefault("QTAIL_FAKE_GENERATOR", "1")

from app import create_app  # noqa: E402
from worker import process_one  # noqa: E402


GENERATION_PAYLOAD = {
    "robot_model": "Franka Panda",
    "control_frequency_hz": 20,
    "sensors": "RGB-D + joint state",
    "training_format": "LeRobot v3",
    "production_backend": "MuJoCo",
    "synthetic_budget": 100000,
    "filename": "procurement_tasks.csv",
    "csv_text": "task,count,success_rate,difficulty,group\nrare_pick,12,0.32,0.91,tail\nstandard_pick,540,0.86,0.22,head\n",
    "claim_acknowledged": True,
    "data_rights": {
        "source_type": "customer_owned",
        "license_basis": "Procurement integration fixture owned by buyer",
        "contains_personal_data": False,
        "retention_days": 30,
        "source_rights_confirmed": True,
        "derivative_rights_confirmed": True,
        "restricted_data_excluded": True,
    },
}


def external_evidence(payload: dict, suffix: str, gate_number: int) -> dict:
    return {
        **payload,
        "evidence_scope": "buyer_external",
        "evidence_issuer": "Buyer Robotics QA",
        "evidence_artifact_sha256": (f"{gate_number + 3:x}" * 64)[:64],
        "buyer_signoff_sha256": (f"{gate_number + 7:x}" * 64)[:64],
        "evidence_observed_at": "2026-07-16T09:00:00+08:00",
        "evidence_notes": f"Buyer-external integration evidence fixture {suffix}; software workflow test only.",
    }


def external_review(suffix: str, gate_number: int) -> dict:
    return {
        "review_note": f"Buyer artifact, signoff hash and scope reviewed for Gate {gate_number} in integration fixture.",
        "verification_reference": f"BUYER-EVIDENCE-{suffix}-G{gate_number}",
        "reviewer_name": "Q-Tail Procurement QA",
    }


class ProcurementCommercialFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app(initialize=True)
        cls.app.config.update(TESTING=True)

    def test_gate_evidence_to_signed_contract(self):
        client = self.app.test_client()
        suffix = f"{int(time.time() * 1000)}-{os.getpid()}"
        admin = {"X-Admin-Token": os.environ["ADMIN_TOKEN"]}

        registered = client.post("/api/auth/register", json={
            "name": "Procurement Buyer",
            "company": "Buyer Robotics",
            "email": f"procurement-{suffix}@example.com",
            "password": "buyer-password-2026",
        })
        self.assertEqual(registered.status_code, 201, registered.get_data(as_text=True))
        user_id = registered.get_json()["user"]["id"]

        application = client.post("/api/api-access", json={
            "role": "采购验证负责人",
            "use_case": "尾部任务采购验证",
            "data_format": "LeRobot v3",
            "monthly_volume": "100,000 units",
            "pilot_goal": "完成四道 Gate 并形成合同就绪记录。",
        }).get_json()["application"]
        self.assertEqual(client.post(f"/api/admin/api-access/{application['id']}/approve", headers=admin, json={}).status_code, 200)

        order = client.post("/api/payment-orders", json={"channel": "alipay"}).get_json()["order"]
        self.assertEqual(client.post(f"/api/payment-orders/{order['id']}/submit", json={"payment_reference": f"PROC-{suffix}"}).status_code, 200)
        self.assertEqual(client.post(f"/api/admin/payment-orders/{order['id']}/confirm", headers=admin, json={}).status_code, 200)

        generated = client.post("/api/generations", json=GENERATION_PAYLOAD)
        self.assertEqual(generated.status_code, 202, generated.get_data(as_text=True))
        job_id = generated.get_json()["job_id"]
        worker_result = process_one(f"unit-procurement-{suffix}", job_id)
        self.assertEqual(worker_result["status"], "completed", worker_result)

        case_response = client.post("/api/procurement-cases", json={
            "generation_job_id": job_id,
            "title": "Rare Pick Pilot",
            "buyer_owner": "Buyer QA Lead",
            "pilot_scope": "3 个尾部抓取任务，完成轨迹、闭环和真机商业验证。",
        })
        self.assertEqual(case_response.status_code, 201, case_response.get_data(as_text=True))
        case_id = case_response.get_json()["case"]["id"]

        premature = client.post(f"/api/procurement-cases/{case_id}/gates/2/evidence", json={})
        self.assertEqual(premature.status_code, 409, premature.get_data(as_text=True))

        failed_gate1 = client.post(f"/api/procurement-cases/{case_id}/gates/1/evidence", json={"trajectory_count": 0})
        self.assertEqual(failed_gate1.status_code, 422, failed_gate1.get_data(as_text=True))
        self.assertIn("trajectory_count_gt_0", failed_gate1.get_json()["error"]["evaluation"]["failed_checks"])

        gate1_payload = {
            "trajectory_count": 480,
            "schema_validation_passed": True,
            "sample_playback_passed": True,
            "dataset_manifest_sha256": "a" * 64,
            "production_log_url": "https://evidence.example/gate1",
        }
        gate1 = client.post(f"/api/procurement-cases/{case_id}/gates/1/evidence", json={**gate1_payload, "evidence_scope": "simulation"})
        self.assertEqual(gate1.status_code, 201, gate1.get_data(as_text=True))
        gate1_id = gate1.get_json()["evidence"]["id"]
        queue = client.get("/api/admin/summary", headers=admin).get_json()
        self.assertIn(gate1_id, [item["id"] for item in queue["procurement_evidence"]])
        self.assertEqual(client.post(f"/api/admin/procurement-evidence/{gate1_id}/approve", headers=admin, json={}).status_code, 200)

        gate2_payload = {
            "same_policy": True,
            "same_budget": True,
            "baseline_name": "inverse-frequency",
            "tail_sr_gain_pp": 6.2,
            "ci95_lower_pp": 1.1,
            "overall_gain_pp": 0.2,
            "head_gain_pp": -0.4,
            "evaluation_episodes": 800,
            "evaluation_report_url": "https://evidence.example/gate2",
        }
        gate2 = client.post(f"/api/procurement-cases/{case_id}/gates/2/evidence", json={**gate2_payload, "evidence_scope": "simulation"})
        self.assertEqual(gate2.status_code, 201, gate2.get_data(as_text=True))
        gate2_id = gate2.get_json()["evidence"]["id"]
        self.assertEqual(client.post(f"/api/admin/procurement-evidence/{gate2_id}/approve", headers=admin, json={}).status_code, 200)

        gate3_payload = {
            "tail_task_count": 3,
            "simulation_episodes_per_condition": 120,
            "real_robot_trials_per_task": 36,
            "unit_cost_reduction_pct": 24,
            "safety_review_passed": True,
            "buyer_acceptance_owner": "Buyer QA Lead",
            "validation_report_url": "https://evidence.example/gate3",
        }
        gate3 = client.post(f"/api/procurement-cases/{case_id}/gates/3/evidence", json={**gate3_payload, "evidence_scope": "simulation"})
        self.assertEqual(gate3.status_code, 201, gate3.get_data(as_text=True))
        gate3_id = gate3.get_json()["evidence"]["id"]
        self.assertEqual(client.post(f"/api/admin/procurement-evidence/{gate3_id}/approve", headers=admin, json={}).status_code, 200)

        cases = client.get("/api/procurement-cases").get_json()["cases"]
        current = next(item for item in cases if item["id"] == case_id)
        self.assertEqual(current["status"], "active")
        self.assertTrue(all(gate["status"] == "approved" for gate in current["gates"]))
        self.assertEqual(current["contract_evidence"]["missing_gates"], [1, 2, 3])

        blocked_contract = client.post(f"/api/admin/procurement-cases/{case_id}/issue-contract", headers=admin, json={})
        self.assertEqual(blocked_contract.status_code, 409, blocked_contract.get_data(as_text=True))
        self.assertEqual(blocked_contract.get_json()["error"]["code"], "external_evidence_required")

        compliance = client.put("/api/compliance", json={
            "organization_legal_name": "Buyer Robotics Co., Ltd.",
            "security_contact_email": f"security-{suffix}@example.com",
            "deployment_boundary": "customer_vpc",
            "data_residency": "中国大陆",
            "retention_days": 90,
            "deletion_sla_days": 15,
            "source_rights_confirmed": True,
            "derivative_rights_confirmed": True,
            "restricted_data_excluded": True,
            "subprocessor_reviewed": True,
            "terms_accepted": True,
            "privacy_acknowledged": True,
            "dpa_accepted": True,
        })
        self.assertEqual(compliance.status_code, 200, compliance.get_data(as_text=True))
        self.assertFalse(compliance.get_json()["ready_for_contract"])
        compliance_queue = client.get("/api/admin/summary", headers=admin).get_json()["compliance_profiles"]
        self.assertIn(user_id, [item["user_id"] for item in compliance_queue])
        approved_compliance = client.post(f"/api/admin/compliance-profiles/{user_id}/approve", headers=admin, json={"review_note": "Integration DPA and security boundary approved"})
        self.assertEqual(approved_compliance.status_code, 200, approved_compliance.get_data(as_text=True))
        self.assertEqual(approved_compliance.get_json()["profile"]["status"], "approved")
        current = next(item for item in client.get("/api/procurement-cases").get_json()["cases"] if item["id"] == case_id)
        self.assertEqual(current["status"], "active")
        self.assertTrue(current["compliance"]["ready_for_contract"])

        simulated_contract = client.post(f"/api/admin/procurement-cases/{case_id}/issue-contract", headers=admin, json={})
        self.assertEqual(simulated_contract.status_code, 409, simulated_contract.get_data(as_text=True))
        self.assertEqual(simulated_contract.get_json()["error"]["code"], "external_evidence_required")
        self.assertEqual(simulated_contract.get_json()["error"]["missing_gates"], [1, 2, 3])

        external_gate_ids = []
        for gate_number, gate_payload in ((1, gate1_payload), (2, gate2_payload), (3, gate3_payload)):
            external = client.post(
                f"/api/procurement-cases/{case_id}/gates/{gate_number}/evidence",
                json=external_evidence(gate_payload, suffix, gate_number),
            )
            self.assertEqual(external.status_code, 201, external.get_data(as_text=True))
            external_id = external.get_json()["evidence"]["id"]
            external_gate_ids.append(external_id)
            if gate_number == 1:
                missing_review = client.post(
                    f"/api/admin/procurement-evidence/{external_id}/approve",
                    headers=admin,
                    json={"review_note": "Too little metadata"},
                )
                self.assertEqual(missing_review.status_code, 400, missing_review.get_data(as_text=True))
                self.assertEqual(missing_review.get_json()["error"]["code"], "external_evidence_verification_required")
            approved_external = client.post(
                f"/api/admin/procurement-evidence/{external_id}/approve",
                headers=admin,
                json=external_review(suffix, gate_number),
            )
            self.assertEqual(approved_external.status_code, 200, approved_external.get_data(as_text=True))
            self.assertTrue(approved_external.get_json()["evidence"]["contract_eligible"])

        current = next(item for item in client.get("/api/procurement-cases").get_json()["cases"] if item["id"] == case_id)
        self.assertEqual(current["status"], "contract_ready")
        self.assertTrue(current["contract_evidence"]["ready"])
        self.assertEqual(current["contract_evidence"]["missing_gates"], [])

        issued = client.post(f"/api/admin/procurement-cases/{case_id}/issue-contract", headers=admin, json={})
        self.assertEqual(issued.status_code, 201, issued.get_data(as_text=True))
        contract_id = issued.get_json()["contract"]["id"]

        draft = client.get(f"/api/procurement-contracts/{contract_id}/draft")
        self.assertEqual(draft.status_code, 200, draft.get_data(as_text=True))
        self.assertIn("text/markdown", draft.content_type)
        self.assertIn("草案，不是已签署合同", draft.get_data(as_text=True))
        self.assertIn("验收快照 SHA-256", draft.get_data(as_text=True))
        self.assertIn("合规资料 SHA-256", draft.get_data(as_text=True))
        self.assertIn("Rare Pick Pilot", draft.get_data(as_text=True))

        anonymous = self.app.test_client()
        self.assertEqual(anonymous.get(f"/api/procurement-contracts/{contract_id}/draft").status_code, 401)
        other = self.app.test_client()
        self.assertEqual(other.post("/api/auth/register", json={
            "name": "Other Buyer",
            "company": "Other Robotics",
            "email": f"other-procurement-{suffix}@example.com",
            "password": "other-buyer-password-2026",
        }).status_code, 201)
        self.assertEqual(other.get(f"/api/procurement-contracts/{contract_id}/draft").status_code, 404)

        incomplete_signed = client.post(f"/api/admin/procurement-contracts/{contract_id}/mark-signed", headers=admin, json={"contract_reference": f"BUYER-MSA-{suffix}"})
        self.assertEqual(incomplete_signed.status_code, 400, incomplete_signed.get_data(as_text=True))
        self.assertEqual(incomplete_signed.get_json()["error"]["code"], "executed_contract_metadata_required")
        shared_signature_hash = "d" * 64
        duplicate_signature_proofs = client.post(f"/api/admin/procurement-contracts/{contract_id}/mark-signed", headers=admin, json={
            "contract_reference": f"BUYER-MSA-{suffix}",
            "executed_document_sha256": "f" * 64,
            "provider_signatory": "Q-Tail Authorized Representative",
            "provider_signature_sha256": shared_signature_hash,
            "buyer_signatory": "Buyer Robotics Authorized Representative",
            "buyer_signature_sha256": shared_signature_hash,
            "effective_date": "2026-07-16",
        })
        self.assertEqual(duplicate_signature_proofs.status_code, 400, duplicate_signature_proofs.get_data(as_text=True))
        self.assertEqual(duplicate_signature_proofs.get_json()["error"]["code"], "independent_signature_proofs_required")
        signed = client.post(f"/api/admin/procurement-contracts/{contract_id}/mark-signed", headers=admin, json={
            "contract_reference": f"BUYER-MSA-{suffix}",
            "executed_document_sha256": "f" * 64,
            "provider_signatory": "Q-Tail Authorized Representative",
            "provider_signature_sha256": "d" * 64,
            "buyer_signatory": "Buyer Robotics Authorized Representative",
            "buyer_signature_sha256": "e" * 64,
            "effective_date": "2026-07-16",
        })
        self.assertEqual(signed.status_code, 200, signed.get_data(as_text=True))
        self.assertEqual(signed.get_json()["contract"]["status"], "signed")
        self.assertEqual(signed.get_json()["contract"]["provider_signature_sha256"], "d" * 64)
        self.assertEqual(signed.get_json()["contract"]["buyer_signature_sha256"], "e" * 64)
        self.assertTrue(signed.get_json()["contract"]["execution_verified"])

        final_case = next(item for item in client.get("/api/procurement-cases").get_json()["cases"] if item["id"] == case_id)
        self.assertEqual(final_case["status"], "contracted")
        self.assertEqual(final_case["contract"]["status"], "signed")
        self.assertTrue(final_case["contract"]["execution_verified"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
