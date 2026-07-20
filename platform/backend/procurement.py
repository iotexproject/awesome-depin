from __future__ import annotations

from datetime import datetime
from typing import Any


GATE_DEFINITIONS = {
    0: {
        "label": "重新定义商品",
        "acceptance": "声明边界、输入哈希与可审计交付包齐备",
    },
    1: {
        "label": "产出可训练轨迹",
        "acceptance": "轨迹数大于 0，Schema 与样本回放通过，交付清单哈希和后端日志齐备",
    },
    2: {
        "label": "完成闭环对照",
        "acceptance": "Tail SR ≥ +5 pp、95% CI 下界 > 0、overall ≥ -1 pp、head ≥ -2 pp",
    },
    3: {
        "label": "真机和商业验证",
        "acceptance": "3–5 个尾部任务、每条件仿真 ≥100、每任务真机 ≥30、单位成本下降 ≥20%",
    },
}


def _number(payload: dict, key: str) -> float | None:
    try:
        value = payload.get(key)
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _truthy(payload: dict, key: str) -> bool:
    return payload.get(key) is True


def _present(payload: dict, key: str) -> bool:
    return bool(str(payload.get(key) or "").strip())


def _sha256(payload: dict, key: str) -> bool:
    value = str(payload.get(key) or "")
    return len(value) == 64 and all(char in "0123456789abcdefABCDEF" for char in value)


def _iso_datetime(payload: dict, key: str) -> bool:
    value = str(payload.get(key) or "").strip()
    if not value:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def evaluate_gate_evidence(gate_number: int, payload: dict[str, Any]) -> dict:
    evidence_scope = str(payload.get("evidence_scope") or "simulation")
    common_checks = {
        "evidence_scope_valid": evidence_scope in {"simulation", "buyer_external"},
    }
    if evidence_scope == "buyer_external":
        common_checks.update({
            "evidence_issuer_present": _present(payload, "evidence_issuer"),
            "evidence_artifact_sha256": _sha256(payload, "evidence_artifact_sha256"),
            "buyer_signoff_sha256": _sha256(payload, "buyer_signoff_sha256"),
            "evidence_observed_at_iso8601": _iso_datetime(payload, "evidence_observed_at"),
        })

    if gate_number == 1:
        trajectory_count = _number(payload, "trajectory_count")
        checks = {
            "trajectory_count_gt_0": trajectory_count is not None and trajectory_count > 0,
            "schema_validation_passed": _truthy(payload, "schema_validation_passed"),
            "sample_playback_passed": _truthy(payload, "sample_playback_passed"),
            "dataset_manifest_sha256": _sha256(payload, "dataset_manifest_sha256"),
            "production_log_url": _present(payload, "production_log_url"),
        }
    elif gate_number == 2:
        tail = _number(payload, "tail_sr_gain_pp")
        ci_lower = _number(payload, "ci95_lower_pp")
        overall = _number(payload, "overall_gain_pp")
        head = _number(payload, "head_gain_pp")
        episodes = _number(payload, "evaluation_episodes")
        checks = {
            "same_policy": _truthy(payload, "same_policy"),
            "same_budget": _truthy(payload, "same_budget"),
            "baseline_named": _present(payload, "baseline_name"),
            "tail_sr_gain_pp_gte_5": tail is not None and tail >= 5,
            "ci95_lower_pp_gt_0": ci_lower is not None and ci_lower > 0,
            "overall_gain_pp_gte_minus_1": overall is not None and overall >= -1,
            "head_gain_pp_gte_minus_2": head is not None and head >= -2,
            "evaluation_episodes_gt_0": episodes is not None and episodes > 0,
            "evaluation_report_url": _present(payload, "evaluation_report_url"),
        }
    elif gate_number == 3:
        tail_tasks = _number(payload, "tail_task_count")
        simulation = _number(payload, "simulation_episodes_per_condition")
        trials = _number(payload, "real_robot_trials_per_task")
        cost = _number(payload, "unit_cost_reduction_pct")
        checks = {
            "tail_task_count_3_to_5": tail_tasks is not None and 3 <= tail_tasks <= 5,
            "simulation_episodes_per_condition_gte_100": simulation is not None and simulation >= 100,
            "real_robot_trials_per_task_gte_30": trials is not None and trials >= 30,
            "unit_cost_reduction_pct_gte_20": cost is not None and cost >= 20,
            "safety_review_passed": _truthy(payload, "safety_review_passed"),
            "buyer_acceptance_owner": _present(payload, "buyer_acceptance_owner"),
            "validation_report_url": _present(payload, "validation_report_url"),
        }
    else:
        raise ValueError("gate_number_must_be_1_to_3")

    checks = {**common_checks, **checks}
    failed = [key for key, passed in checks.items() if not passed]
    status = "passed" if not failed else "failed"
    return {
        "gate_number": gate_number,
        "label": GATE_DEFINITIONS[gate_number]["label"],
        "acceptance": GATE_DEFINITIONS[gate_number]["acceptance"],
        "checks": checks,
        "failed_checks": failed,
        "status": status,
        "evidence_scope": evidence_scope,
        "contract_evidence_eligible": status == "passed" and evidence_scope == "buyer_external",
    }
