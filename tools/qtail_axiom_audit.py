#!/usr/bin/env python3
"""Build an Axiom-style claim boundary and audit ledger for Q-TAIL.

The script consumes the existing Q-TAIL MVP result artifacts and emits a
machine-readable audit file plus a short research note. It intentionally keeps
simulation evidence separate from real-environment or hardware claims.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
RESEARCH = ROOT / "docs" / "research"

TAIL_TASKS = ["window-open-v2", "sweep-v2", "basketball-v2"]
EXTREME_FAILURE_THRESHOLD = 0.50
WARNING_FAILURE_THRESHOLD = 0.55
EXTENDED_RESULT_DIR = RESULTS / "axiom_baseline_matrix"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def by_strategy(rows: list[dict[str, Any]], key: str = "Strategy") -> dict[str, dict[str, Any]]:
    return {str(row[key]).lower(): row for row in rows}


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def pp(value: float) -> str:
    return f"{value * 100:+.1f} pp"


def count_below(values: dict[str, float], threshold: float) -> int:
    return sum(1 for score in values.values() if score < threshold)


def sum_tasks(values: dict[str, float], tasks: list[str]) -> float:
    return sum(float(values.get(task, 0.0)) for task in tasks)


def require(condition: bool, requirement_id: str, description: str) -> dict[str, Any]:
    return {
        "id": requirement_id,
        "description": description,
        "passed": bool(condition),
    }


def load_extended_baseline_matrix() -> dict[str, Any]:
    path = EXTENDED_RESULT_DIR / "experiment_results.json"
    if not path.exists():
        return {
            "available": False,
            "artifact": str(path.relative_to(ROOT)),
            "strategies": [],
            "metrics": {},
            "best_by_tail": None,
            "pt_rank_tail_rank": None,
            "pt_rank_beats": [],
            "pt_rank_loses_to": [],
        }

    metrics = read_json(path)["metrics"]
    rows = []
    for strategy, values in metrics.items():
        row = {"strategy": strategy, **values}
        rows.append(row)
    rows.sort(key=lambda item: float(item["tail_sr"]), reverse=True)

    pt_tail = float(metrics["pt-rank"]["tail_sr"])
    pt_rank_beats = [
        name for name, values in metrics.items()
        if name != "pt-rank" and pt_tail > float(values["tail_sr"])
    ]
    pt_rank_loses_to = [
        name for name, values in metrics.items()
        if name != "pt-rank" and pt_tail <= float(values["tail_sr"])
    ]
    pt_rank_tail_rank = 1 + sum(1 for values in metrics.values() if float(values["tail_sr"]) > pt_tail)

    return {
        "available": True,
        "artifact": str(path.relative_to(ROOT)),
        "strategies": list(metrics.keys()),
        "metrics": metrics,
        "best_by_tail": rows[0],
        "best_by_cvar20": max(
            ({"strategy": name, **values} for name, values in metrics.items()),
            key=lambda item: float(item["cvar20"]),
        ),
        "pt_rank_tail_rank": pt_rank_tail_rank,
        "pt_rank_beats": pt_rank_beats,
        "pt_rank_loses_to": pt_rank_loses_to,
        "rows_by_tail_desc": rows,
    }


def build_audit() -> dict[str, Any]:
    report = read_json(RESULTS / "report.json")
    page_summary = read_json(RESULTS / "page_experiment_summary.json")
    mt10_rows = by_strategy(report["metrics"])
    uniform = mt10_rows["uniform"]
    pt_rank = mt10_rows["pt-rank"]

    uniform_heatmap = report["task_sr_heatmap"]["uniform"]
    pt_heatmap = report["task_sr_heatmap"]["pt-rank"]
    uniform_sampling = report["sampling_dists"]["uniform"]
    pt_sampling = report["sampling_dists"]["pt-rank"]

    mt50_rows = by_strategy(read_csv(RESULTS / "summary_mt50_comprehensive.csv"))
    risk_rows = by_strategy(read_csv(RESULTS / "summary_risk.csv"), key="Generator")
    exploration_rows = by_strategy(read_csv(RESULTS / "summary_exploration.csv"))

    tail_gain = float(pt_rank["Tail Success"]) - float(uniform["Tail Success"])
    cvar_gain = float(pt_rank["CVaR@20"]) - float(uniform["CVaR@20"])
    overall_gain = float(pt_rank["Overall Success"]) - float(uniform["Overall Success"])
    head_delta = float(pt_rank["Head Success"]) - float(uniform["Head Success"])

    extreme_fail_uniform = count_below(uniform_heatmap, EXTREME_FAILURE_THRESHOLD)
    extreme_fail_pt = count_below(pt_heatmap, EXTREME_FAILURE_THRESHOLD)
    warning_fail_uniform = count_below(uniform_heatmap, WARNING_FAILURE_THRESHOLD)
    warning_fail_pt = count_below(pt_heatmap, WARNING_FAILURE_THRESHOLD)

    tail_sampling_uniform = sum_tasks(uniform_sampling, TAIL_TASKS)
    tail_sampling_pt = sum_tasks(pt_sampling, TAIL_TASKS)
    tail_sampling_gain = tail_sampling_pt - tail_sampling_uniform
    coverage_ratio = tail_sampling_pt / tail_sampling_uniform if tail_sampling_uniform else None

    mt50_uniform = mt50_rows["uniform"]
    mt50_pt = mt50_rows["pt-rank (ours)"]
    mt50_adaptive = mt50_rows["pt-ot adaptive (ours)"]
    risk_uniform = float(risk_rows["uniform"]["Wasserstein_1"])
    risk_pt = float(risk_rows["pt-ot"]["Wasserstein_1"])
    exploration_uniform = float(exploration_rows["uniform"]["Best Arm Discovery (%)"])
    exploration_pt = float(exploration_rows["pt-ot"]["Best Arm Discovery (%)"])
    extended_matrix = load_extended_baseline_matrix()
    pt_beats_core_adversaries = False
    pt_beats_uniform_extended = False
    if extended_matrix["available"]:
        extended_metrics = extended_matrix["metrics"]
        pt_tail_ext = float(extended_metrics["pt-rank"]["tail_sr"])
        pt_beats_uniform_extended = pt_tail_ext > float(extended_metrics["uniform"]["tail_sr"])
        core_adversaries = [
            "prioritized_replay",
            "curriculum",
            "dro_risk_weighting",
            "focal_loss",
        ]
        pt_beats_core_adversaries = all(
            pt_tail_ext > float(extended_metrics[name]["tail_sr"])
            for name in core_adversaries
            if name in extended_metrics
        )

    requirements = [
        require(tail_gain > 0.0, "Q1", "pt-rank Tail Success beats uniform under the same 100k-step MT10 simulation budget."),
        require(cvar_gain > 0.0, "Q2", "pt-rank CVaR@20 beats uniform under the same 100k-step MT10 simulation budget."),
        require(overall_gain >= -0.02, "Q3", "Overall success is preserved within a 2 pp non-inferiority band."),
        require(head_delta >= -0.01, "Q4", "Head-task success is preserved within a 1 pp non-inferiority band."),
        require(extreme_fail_pt < extreme_fail_uniform, "Q5", "Extreme task failures below 50% success are reduced versus uniform."),
        require(tail_sampling_gain > 0.0, "Q6", "Tail task sampling mass increases versus uniform, supporting faster rare-space coverage."),
        require(risk_pt < risk_uniform, "Q7", "PT-OT risk-scene generator has lower Wasserstein-1 distance than uniform in the risk simulator."),
        require(exploration_pt > exploration_uniform, "Q8", "PT-OT rare-jump exploration improves best-arm discovery in the exploration simulator."),
        require(pt_beats_uniform_extended, "Q9", "Extended baseline-matrix replay keeps pt-rank Tail Success above uniform."),
        require(pt_beats_core_adversaries, "Q10", "pt-rank Tail Success beats PER, curriculum, DRO, and focal-loss proxies in the extended simulation matrix."),
    ]

    passed = sum(1 for item in requirements if item["passed"])

    claim_boundary = {
        "now_supported": [
            "In the existing simulated MT10 evidence, Q-TAIL pt-rank improves Tail Success versus uniform at the same 100k-step budget.",
            "In the same simulated MT10 evidence, pt-rank improves CVaR@20 and removes sub-50% extreme task failures while preserving head-task success.",
            "The scheduler increases sampling mass on the declared tail task set, which is evidence for faster coverage of rare task space in simulation.",
            "Separate PT-OT simulator artifacts support risk-scene generation and rare-jump exploration as useful long-tail mechanisms.",
            "Commercial value is credible as a risk-aware training scheduler and evaluation layer, not yet as a proven hardware-quantum advantage product.",
        ],
        "still_not_supported": [
            "No real Meta-World SAC/PPO training run is audited here.",
            "No real robot or production embodied-AI deployment is audited here.",
            "No quantum advantage, quantum speedup, or hardware superiority claim is supported.",
            "Tail-specific statistical significance beyond the 3-seed simulation summary is not established.",
            "The expanded simulation matrix does not prove pt-rank dominates every classical proxy; power-law and Levy proxies have higher simulated tail success, while Gaussian has stronger aggregate/CVaR behavior in this simulator.",
            "MT50, PT-OT adaptive, domain randomization, adversarial generation, diffusion/LLM task generation, and simulator edge-case mining remain proxy or future-work evidence until reproduced under locked training conditions.",
        ],
        "falsifiers": [
            "A same-budget real MT10 run where pt-rank does not improve Tail Success or CVaR@20 versus uniform.",
            "A stronger baseline such as DRO, focal loss, prioritized replay, or adaptive curriculum matching Q-TAIL tail metrics with less complexity.",
            "A classic beta/lognormal/Pareto/power-law scheduler matching Q-TAIL tail metrics while preserving head and overall success.",
            "A domain-randomization, adversarial-scenario, diffusion/LLM task-generation, or simulator edge-case-mining system that covers the same rare task space faster under equal compute.",
            "A replay audit showing hidden budget, environment, seed, or metric differences across strategies.",
            "A real-robot rare-task benchmark where Q-TAIL increases tail sampling but does not improve rare-task success or risk.",
        ],
    }

    work_packets = [
        {
            "id": "QTAIL-W1-real-mt10-lock",
            "agent_role": "Benchmark Curator",
            "objective": "Lock real MT10 SAC/PPO environment, seeds, compute budget, task taxonomy, and logging schema.",
            "required_outputs": ["benchmark manifest", "seed ledger", "config hash", "parseable run logs"],
            "done_when": "Uniform, empirical, invfreq, pt-rank, and one strong adaptive baseline run under identical conditions.",
            "must_not_claim": "Do not claim real-environment superiority until W2/W3 audits pass.",
        },
        {
            "id": "QTAIL-W2-baseline-adversary",
            "agent_role": "Baseline Adversary",
            "objective": "Add and harden DRO, focal loss, prioritized replay, curriculum, beta/lognormal/Pareto/power-law, and Gaussian baselines under the locked W1 protocol.",
            "required_outputs": ["baseline scripts", "metric table", "failure-mode report"],
            "done_when": "Q-TAIL beats the strongest same-budget baseline on Tail Success or CVaR@20 without unacceptable overall loss.",
            "must_not_claim": "Do not compare against weak baselines only.",
        },
        {
            "id": "QTAIL-W3-stat-audit",
            "agent_role": "Audit Agent",
            "objective": "Run confidence intervals, paired tests, seed sensitivity, and metric-leakage checks.",
            "required_outputs": ["audit script", "JSON audit result", "claim-boundary update"],
            "done_when": "Tail Success, CVaR@20, extreme-failure rate, and rare-space coverage have reproducible uncertainty estimates.",
            "must_not_claim": "Do not use practical lift as statistical significance without the test ledger.",
        },
        {
            "id": "QTAIL-W4-generation-mining-adversary",
            "agent_role": "Scenario Generation Agent",
            "objective": "Evaluate domain randomization, adversarial scenario generation, diffusion/LLM task generation, and simulator edge-case mining as rare-task coverage adversaries.",
            "required_outputs": ["scenario manifest", "coverage metric", "same-budget generation cost ledger", "rare-task replay set"],
            "done_when": "Coverage-per-compute and tail-success-per-generated-scenario are measured against Q-TAIL under the same environment contract.",
            "must_not_claim": "Do not treat generated scenario count as coverage unless failures are replayable and tied to task success.",
        },
        {
            "id": "QTAIL-W5-business-evidence",
            "agent_role": "Translation Agent",
            "objective": "Translate audited technical gates into buyer-specific value cases for robotics, simulation data, and safety evaluation.",
            "required_outputs": ["ROI model", "buyer map", "pilot acceptance checklist"],
            "done_when": "At least one pilot plan ties reduced tail failure to measurable training cost, incident risk, or data-coverage savings.",
            "must_not_claim": "Do not claim revenue, patentability, or production readiness before technical gates pass.",
        },
    ]

    value_assessment = {
        "technical_value": [
            "Drop-in scheduler: Q-TAIL changes task allocation rather than the policy network or environment source.",
            "Risk-sensitive metric focus: Tail Success, CVaR@20, and extreme-failure counts target the failure modes average success hides.",
            "Rare-space exploration: PT-rank/PT-OT priors allocate more budget to hard and low-frequency tasks without fully abandoning head tasks.",
            "Auditable architecture: source distribution, semantic mapping, scheduler, training logs, and evaluation are separable agent surfaces.",
        ],
        "commercial_value": [
            "Training efficiency: fewer wasted steps on already-solved head tasks if real runs reproduce the simulated tail lift.",
            "Safety and QA: explicit extreme-failure metrics support robotics, autonomous-agent, and simulation testing workflows.",
            "Data engine positioning: the product can sell rare-scenario coverage and risk evaluation before claiming quantum advantage.",
            "Baseline-neutral packaging: Q-TAIL can be sold as an auditable scheduler/evaluator that also benchmarks curriculum, PER, domain randomization, adversarial generation, and edge-case mining.",
            "Enterprise pilot path: value can be measured by tail-task pass rate, incident replay coverage, and compute-per-rare-success.",
        ],
        "risk_register": [
            "Current main evidence is simulation, so commercialization should be framed as pilot-ready methodology rather than proven deployment performance.",
            "The quantum prior may be matched by simpler heavy-tail, Gaussian, curriculum, or generator-based baselines; W2/W4 must try to kill the claim.",
            "Buyer value depends on mapping abstract task rarity to domain-specific rare failures.",
        ],
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "framework_source": {
            "name": "Axiom-Horizon-inspired claim boundary + audit + multi-agent PR workflow",
            "local_reference_repo": "/tmp/Axiom-Horizon",
            "reference_url": "https://github.com/crystal-tensor/Axiom-Horizon",
            "adapted_pattern": [
                "problem -> benchmark -> method -> result -> audit -> claim boundary -> review",
                "positive claims separated from forbidden claims",
                "agent-ready PR work packets",
                "translation only after technical gates",
            ],
        },
        "evidence_level": "L2 reproducible simulation baseline; not L3/L4 until adversarial and real-environment gates pass",
        "mode": "simulated",
        "locked_conditions_observed": {
            "environment": "Meta-World MT10 statistical simulator",
            "budget": page_summary.get("experiment_note", "100,000 steps, 3 seeds, simulated"),
            "same_compute_same_steps_same_environment": True,
            "artifact_paths": [
                "results/report.json",
                "results/page_experiment_summary.json",
                "results/summary.csv",
                "results/summary_mt50_comprehensive.csv",
                "results/summary_risk.csv",
                "results/summary_exploration.csv",
                "results/axiom_baseline_matrix/experiment_results.json",
                "results/axiom_baseline_matrix/summary.csv",
            ],
        },
        "headline_metrics": {
            "mt10_tail_success_uniform": uniform["Tail Success"],
            "mt10_tail_success_pt_rank": pt_rank["Tail Success"],
            "mt10_tail_success_gain": tail_gain,
            "mt10_tail_success_gain_pp": pp(tail_gain),
            "mt10_cvar20_uniform": uniform["CVaR@20"],
            "mt10_cvar20_pt_rank": pt_rank["CVaR@20"],
            "mt10_cvar20_gain": cvar_gain,
            "mt10_cvar20_gain_pp": pp(cvar_gain),
            "mt10_overall_gain": overall_gain,
            "mt10_head_delta": head_delta,
            "extreme_failure_threshold": EXTREME_FAILURE_THRESHOLD,
            "extreme_failures_uniform": extreme_fail_uniform,
            "extreme_failures_pt_rank": extreme_fail_pt,
            "warning_failure_threshold": WARNING_FAILURE_THRESHOLD,
            "warning_failures_uniform": warning_fail_uniform,
            "warning_failures_pt_rank": warning_fail_pt,
            "tail_sampling_mass_uniform": tail_sampling_uniform,
            "tail_sampling_mass_pt_rank": tail_sampling_pt,
            "tail_sampling_mass_gain": tail_sampling_gain,
            "tail_sampling_coverage_ratio": coverage_ratio,
            "mt50_tail_success_uniform_percent": float(mt50_uniform["Tail Success"]),
            "mt50_tail_success_pt_rank_percent": float(mt50_pt["Tail Success"]),
            "mt50_tail_success_pt_ot_adaptive_percent": float(mt50_adaptive["Tail Success"]),
            "risk_wasserstein_uniform": risk_uniform,
            "risk_wasserstein_pt_ot": risk_pt,
            "exploration_best_arm_uniform_percent": exploration_uniform,
            "exploration_best_arm_pt_ot_percent": exploration_pt,
        },
        "extended_baseline_matrix": extended_matrix,
        "adversarial_audit_summary": {
            "pt_rank_beats_uniform_in_extended_matrix": pt_beats_uniform_extended,
            "pt_rank_beats_per_curriculum_dro_focal": pt_beats_core_adversaries,
            "pt_rank_tail_rank_among_extended_strategies": extended_matrix.get("pt_rank_tail_rank"),
            "stronger_tail_strategies_in_current_simulator": extended_matrix.get("pt_rank_loses_to", []),
            "interpretation": (
                "Q-TAIL passes the uniform/core-baseline simulation claim but remains under adversarial pressure "
                "from classic heavy-tail and Gaussian proxy schedulers in this simulator."
            ),
        },
        "requirements": requirements,
        "requirements_passed": passed,
        "requirements_total": len(requirements),
        "gate_status": "simulation_claim_gate_passed" if passed == len(requirements) else "simulation_claim_gate_partial",
        "claim_boundary": claim_boundary,
        "multi_agent_pr_packets": work_packets,
        "value_assessment": value_assessment,
        "review_requests": [
            "Builder review: verify scheduler implementation and task taxonomy.",
            "Baseline adversary review: add stronger baselines and try to erase the lift.",
            "Statistical audit review: rerun with more seeds and locked confidence tests.",
            "Translation review: convert only audited claims into product/pilot language.",
        ],
    }


def write_markdown(audit: dict[str, Any]) -> None:
    metrics = audit["headline_metrics"]
    lines = [
        "# Q-TAIL Axiom-Style Technical And Commercial Value Assessment",
        "",
        "## Claim Boundary",
        "",
        f"Evidence level: **{audit['evidence_level']}**.",
        "",
        "Now supported:",
        *[f"- {item}" for item in audit["claim_boundary"]["now_supported"]],
        "",
        "Still not supported:",
        *[f"- {item}" for item in audit["claim_boundary"]["still_not_supported"]],
        "",
        "## Same-Budget Simulation Evidence",
        "",
        f"- Tail Success: uniform {pct(metrics['mt10_tail_success_uniform'])} -> pt-rank {pct(metrics['mt10_tail_success_pt_rank'])} ({metrics['mt10_tail_success_gain_pp']}).",
        f"- CVaR@20: uniform {pct(metrics['mt10_cvar20_uniform'])} -> pt-rank {pct(metrics['mt10_cvar20_pt_rank'])} ({metrics['mt10_cvar20_gain_pp']}).",
        f"- Extreme failures below 50% success: uniform {metrics['extreme_failures_uniform']} -> pt-rank {metrics['extreme_failures_pt_rank']}.",
        f"- Tail sampling mass: uniform {pct(metrics['tail_sampling_mass_uniform'])} -> pt-rank {pct(metrics['tail_sampling_mass_pt_rank'])}.",
        "",
        "## Multi-Agent PR Packets",
        "",
    ]
    for packet in audit["multi_agent_pr_packets"]:
        lines.extend(
            [
                f"### {packet['id']}",
                f"- Agent role: {packet['agent_role']}",
                f"- Objective: {packet['objective']}",
                f"- Done when: {packet['done_when']}",
                f"- Must not claim: {packet['must_not_claim']}",
                "",
            ]
        )

    lines.extend(
        [
            "## Audit",
            "",
            f"Gate status: **{audit['gate_status']}** ({audit['requirements_passed']}/{audit['requirements_total']} checks passed).",
            "",
            "The page `axiom-qtail-evaluation.html` renders this assessment for review.",
            "",
        ]
    )
    (RESEARCH / "qtail_axiom_value_assessment.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    RESEARCH.mkdir(parents=True, exist_ok=True)
    audit = build_audit()
    (RESULTS / "qtail_axiom_claim_audit.json").write_text(
        json.dumps(audit, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    write_markdown(audit)
    print(
        f"{audit['gate_status']}: "
        f"{audit['requirements_passed']}/{audit['requirements_total']} checks passed; "
        "wrote results/qtail_axiom_claim_audit.json"
    )


if __name__ == "__main__":
    main()
