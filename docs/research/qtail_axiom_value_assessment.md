# Q-Tail-for-AI Same-Budget Proof And Value Assessment

This note records the corrected interpretation of the Axiom-Horizon-inspired
method: use claim boundaries, audits, and PR-sized follow-up work as a research
discipline, not as branding.

## Current Proof

Artifact: `results/qtail_same_budget_proof/same_budget_proof.json`

Protocol:

- same MT10-style long-tail task simulator;
- same 100,000 scheduler decisions per strategy;
- same paired seed environment perturbations;
- identical task learning dynamics across strategies;
- strategies may only change allocation;
- generation/mining methods pay explicit budget-overhead multipliers.

Headline result versus uniform:

- Tail Success: +12.29 percentage points.
- CVaR@20: +13.70 percentage points.
- Severe failures below 35% final success: 2.0 -> 0.0.
- Rare coverage, defined as all tail tasks reaching 40% success: 0.0% -> 62.5%.

## Strong Baseline Boundary

The proof does not claim that Q-Tail maximizes tail success against every
possible hand-tuned heavy-tail distribution. Pareto heavy-tail is a strong
tail-only adversary in the current simulator, but it collapses head success and
CVaR. Q-Tail's claim is balanced tail improvement and severe-failure reduction
under an equal budget.

## Not Claimed

- Real Meta-World SAC/PPO superiority.
- Real robot deployment performance.
- Quantum advantage or quantum speedup.
- Dominance over every possible tuned heavy-tail scheduler.

## Next PR Packets

- Benchmark curator: replace this simulator with real Meta-World SAC/PPO runs.
- Baseline adversary: tune beta/lognormal/Pareto/curriculum/PER/domain-randomization baselines.
- Scenario generation agent: attach diffusion/LLM/adversarial/edge-case generation with explicit cost ledgers.
- Audit agent: rerun paired tests, bootstrap intervals, leakage checks, and page refresh in CI.
