from __future__ import annotations

import sys
import unittest
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from gates import evaluate_request  # noqa: E402


BASE = {
    "robot_model": "Franka Panda",
    "control_frequency_hz": 20,
    "sensors": "RGB-D + joint state",
    "training_format": "RLDS + LeRobot v3",
    "production_backend": "MuJoCo",
    "claim_acknowledged": True,
}


class GateContractTest(unittest.TestCase):
    def test_valid_csv_contract_is_allowed(self):
        result = evaluate_request({**BASE, "csv_text": "task,count\nrare_pick,12\n"})
        self.assertTrue(result["request_allowed"])
        self.assertTrue(result["gate1"]["evidence"]["csv_contract"]["valid"])

    def test_header_only_csv_is_rejected_before_model_execution(self):
        result = evaluate_request({**BASE, "csv_text": "task,count\n"})
        self.assertFalse(result["request_allowed"])
        self.assertFalse(result["gate1"]["evidence"]["csv_contract"]["has_data_row"])

    def test_literal_backslash_n_is_not_a_data_row(self):
        result = evaluate_request({**BASE, "csv_text": r"task,count\nrare_pick,12"})
        self.assertFalse(result["request_allowed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
