from __future__ import annotations

import sys
import unittest
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from procurement import evaluate_gate_evidence  # noqa: E402


class ProcurementThresholdTest(unittest.TestCase):
    def test_gate2_exact_thresholds_pass(self):
        result = evaluate_gate_evidence(2, {
            "same_policy": True,
            "same_budget": True,
            "baseline_name": "inverse-frequency",
            "tail_sr_gain_pp": 5,
            "ci95_lower_pp": 0.01,
            "overall_gain_pp": -1,
            "head_gain_pp": -2,
            "evaluation_episodes": 100,
            "evaluation_report_url": "https://evidence.example/gate2",
        })
        self.assertEqual(result["status"], "passed")
        self.assertFalse(result["contract_evidence_eligible"])

    def test_gate2_ci_lower_bound_must_be_positive(self):
        result = evaluate_gate_evidence(2, {
            "same_policy": True,
            "same_budget": True,
            "baseline_name": "inverse-frequency",
            "tail_sr_gain_pp": 5,
            "ci95_lower_pp": 0,
            "overall_gain_pp": -1,
            "head_gain_pp": -2,
            "evaluation_episodes": 100,
            "evaluation_report_url": "https://evidence.example/gate2",
        })
        self.assertEqual(result["status"], "failed")
        self.assertIn("ci95_lower_pp_gt_0", result["failed_checks"])

    def test_gate3_exact_minimums_pass(self):
        result = evaluate_gate_evidence(3, {
            "tail_task_count": 3,
            "simulation_episodes_per_condition": 100,
            "real_robot_trials_per_task": 30,
            "unit_cost_reduction_pct": 20,
            "safety_review_passed": True,
            "buyer_acceptance_owner": "Buyer QA",
            "validation_report_url": "https://evidence.example/gate3",
        })
        self.assertEqual(result["status"], "passed")
        self.assertFalse(result["contract_evidence_eligible"])

    def test_external_evidence_requires_buyer_signoff_metadata(self):
        result = evaluate_gate_evidence(1, {
            "evidence_scope": "buyer_external",
            "trajectory_count": 10,
            "schema_validation_passed": True,
            "sample_playback_passed": True,
            "dataset_manifest_sha256": "a" * 64,
            "production_log_url": "https://buyer.example/gate1",
        })
        self.assertEqual(result["status"], "failed")
        self.assertIn("buyer_signoff_sha256", result["failed_checks"])
        self.assertFalse(result["contract_evidence_eligible"])

    def test_complete_external_evidence_is_contract_eligible(self):
        result = evaluate_gate_evidence(1, {
            "evidence_scope": "buyer_external",
            "evidence_issuer": "Buyer Robotics QA",
            "evidence_artifact_sha256": "b" * 64,
            "buyer_signoff_sha256": "c" * 64,
            "evidence_observed_at": "2026-07-16T09:00:00+08:00",
            "trajectory_count": 10,
            "schema_validation_passed": True,
            "sample_playback_passed": True,
            "dataset_manifest_sha256": "a" * 64,
            "production_log_url": "https://buyer.example/gate1",
        })
        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["contract_evidence_eligible"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
