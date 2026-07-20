from __future__ import annotations

import csv
import io


TASK_COLUMNS = {"task", "task_id", "skill", "instruction", "scenario", "env", "environment", "name", "States"}
COUNT_COLUMNS = {"count", "n", "episodes", "trajectories", "samples", "frequency", "Raw probabilities(%)", " raw probabilities(%)"}


def inspect_csv(csv_text: str) -> dict:
    try:
        reader = csv.DictReader(io.StringIO(csv_text))
        headers = set(reader.fieldnames or [])
        first_row = next(reader, None)
    except (csv.Error, UnicodeError):
        return {"valid": False, "reason": "csv_parse_error", "headers": []}
    has_task = bool(headers & TASK_COLUMNS)
    has_count = bool(headers & COUNT_COLUMNS)
    has_data_row = bool(first_row and any(str(value or "").strip() for value in first_row.values()))
    return {
        "valid": has_task and has_count and has_data_row,
        "reason": None if has_task and has_count and has_data_row else "task_count_columns_and_one_data_row_required",
        "headers": sorted(headers),
        "has_task_column": has_task,
        "has_count_column": has_count,
        "has_data_row": has_data_row,
    }


def evaluate_request(payload: dict) -> dict:
    trajectory_delivery = payload.get("delivery_product") == "simulation_trajectory_batch"
    required = {
        "robot_model": payload.get("robot_model"),
        "control_frequency_hz": payload.get("control_frequency_hz"),
        "sensors": payload.get("sensors"),
        "training_format": payload.get("training_format"),
        "production_backend": payload.get("production_backend"),
        "csv_text": payload.get("csv_text"),
    }
    missing = [field for field, value in required.items() if value in (None, "", 0)]
    acknowledged = bool(payload.get("claim_acknowledged", True))
    format_name = str(payload.get("training_format") or "")
    recognized_format = "RLDS" in format_name or "LeRobot" in format_name
    csv_check = inspect_csv(str(payload.get("csv_text") or ""))
    gate1_ready = not missing and recognized_format and csv_check["valid"]
    return {
        "gate0": {
            "status": "passed" if acknowledged else "failed",
            "label": "重新定义商品",
            "evidence": (
                "模拟轨迹交付及其非买方证据边界已确认"
                if acknowledged and trajectory_delivery
                else "声明边界已确认"
                if acknowledged
                else "必须确认交付内容与证据边界"
            ),
        },
        "gate1": {
            "status": "contract_ready" if gate1_ready else "input_incomplete",
            "label": "产出可训练轨迹",
            "evidence": {
                "missing_fields": missing,
                "recognized_training_format": recognized_format,
                "csv_contract": csv_check,
                "trajectory_delivery_status": (
                    "verified_qtail_simulation_source_materialization"
                    if trajectory_delivery
                    else "requires_configured_production_backend_execution"
                ),
                "evidence_scope": "simulation" if trajectory_delivery else "specification_only",
                "buyer_gate_passed": False,
            },
        },
        "gate2": {
            "status": "not_validated",
            "label": "完成闭环对照",
            "acceptance": {"tail_sr_gain_pp": 5, "ci_95_lower_gt": 0, "overall_floor_pp": -1, "head_floor_pp": -2},
        },
        "gate3": {
            "status": "not_validated",
            "label": "真机和商业验证",
            "acceptance": {"simulation_episodes_per_condition": 100, "real_robot_trials_per_task": "30-50", "unit_cost_reduction_pct": 20},
        },
        "request_allowed": acknowledged and gate1_ready,
        "commercial_readiness": (
            "gate0_complete_qtail_simulation_delivery_ready_buyer_gate_pending"
            if acknowledged and gate1_ready and trajectory_delivery
            else "gate0_complete_gate1_contract_ready"
            if acknowledged and gate1_ready
            else "blocked"
        ),
    }
