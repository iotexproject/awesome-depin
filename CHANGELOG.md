# Q-TAIL MVP Changelog

## 2026-04-28 (Current Refactoring)

### Project Repositioning
- **Updated Project Goal**: Shifted narrative from "Quantum-driven data generation engine" to "Quantum-guided embodied tail data scheduling and risk evaluation platform" (量子分布引导的具身长尾数据调度与风险评测平台).
- **Removed Overstatements**: Removed claims like "quantum advantage proven" or "direct generation of 3 billion hours of data".

### P0: Experiment Credibility & Reproducibility
- **Modularized Experiments**: Refactored `main.py` using `argparse` to dispatch different execution modes (`simulation`, `real`, `hardware_robustness`, `ablation`).
- **Statistical Rigor**: Implemented paired t-tests and Bootstrap Confidence Intervals in `experiments/mt10_sim.py`.
- **Reproducibility Tracking**: Added `config_hash`, `seed_count`, and explicit `mode="simulated"` markers to all results outputs.
- **Strong Baselines**: Extended sampling logic in `agents/training_agent.py` to support 8 new strategies including `prioritized_replay`, `curriculum`, etc.
- **Simulation Disclaimer**: Clearly marked all simulation outputs and console logs as "simulated baselines", avoiding confusion with real robot or hardware RL training.

### P0: Quantum Source Authenticity
- **Quantum Metric Standardization**: Merged redundant quantum statistics code into `core/quantum_prior.py` (QuantumPriorEngine).
- **Metric Expansion**: Ensured quantum outputs include necessary metrics: `n_qubits`, `shots`, `support_size`, `CV`, `KD`, `KL`, `TV`, `entropy`, `Gini`, `top-k mass`.
- **Gini Calculation Fix**: Added a small epsilon (`1e-12`) to the denominator to prevent negative Gini coefficients.
- **Token Security**: Completely removed hardcoded `QUAFU_TOKEN` from `real_rcs_pt.py`, `quafu_showtime.py`, and `test_token.py`. Replaced with environment variable checks.

### P1: Product Focus & Frontend
- **Frontend Refactoring**: Refactored `index.html` and `qtail-mvp-presentation.html` to dynamically read results from `results/experiment_results.json` using React `useEffect`.
- **Text Consistency**: Replaced old narrative terms with "量子分布引导" (Quantum distribution guided) and "内部模拟信号" (Internal simulated signal).
- **Product Architecture Docs**: Created `docs/product/product_architecture.md` detailing the new 3-layer architecture.
- **Technical Reserve**: Moved non-core features (like auto-annotation) to `appendix/technical_reserve.md`.
- **Engineering Hygiene**: 
  - Added `requirements.txt` and `.gitignore`.
  - Archived patch scripts into `scripts/legacy_patches/`.
  - Secured `upload_server.py` with Bearer Token authentication and file type validation.
  - Fixed npm scripts and Babel syntax checker (`check_syntax.js`).

### P2: Real Robot / High-Fidelity Path
- **Validation Protocol**: Added `docs/experiments/protocol.md` defining the 3-stage validation process (Simulation -> Real RL -> Real Robot).

### Bug Fixes
- Fixed `SyntaxWarning` for invalid escape sequences in `agents/quantum_source_agent.py`, `agents/evaluation_agent.py`, and `experiments/evaluate_hardware_robustness.py`.

---
*Note: All current results in the `results/` folder and displayed on the frontend are generated via the `simulation` mode. Real RL training and real robot verifications are planned for future phases.*