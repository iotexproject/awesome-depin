import os
import yaml
import json
import numpy as np
import pandas as pd
from scipy import stats
import agents.quantum_source_agent as source_agent
import agents.semantic_mapper_agent as mapper_agent
import agents.quantum_scheduler_agent as scheduler_agent
import agents.training_agent as training_agent
import subprocess

def get_git_revision_hash() -> str:
    try:
        return subprocess.check_output(['git', 'rev-parse', 'HEAD'], stderr=subprocess.DEVNULL).decode('ascii').strip()
    except Exception:
        return "unknown"

def load_config(path="config/default.yaml"):
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}

def run(args):
    print("="*60)
    print(" MT10 Simulation Experiment (Statistical Protocol)")
    print("="*60)
    
    config = load_config(args.config)
    
    # Merge CLI args into config
    n_seeds = 10 if config.get("training", {}).get("n_seeds") is None else config.get("training", {}).get("n_seeds", 10)
    if args.seed:
        config.setdefault("training", {})["seed"] = args.seed
        
    print(f"-> Configuration loaded. n_seeds={n_seeds}")
    
    # 1. Quantum Source
    print("\n[1/4] Initializing Quantum Source...")
    source_agent.load_quantum_prior("data")
    # Using simple list as fallback if agent doesn't have get_scheduler_prior
    s_prior = source_agent.get_scheduler_prior() if hasattr(source_agent, "get_scheduler_prior") else [1.0] * 10
    
    # 2. Semantic Mapper
    print("\n[2/4] Initializing Semantic Mapper...")
    taxonomy = mapper_agent.build_mt10_tail_taxonomy()
    tail_scores = mapper_agent.get_tail_scores()
    
    # 3. Quantum Scheduler & Training Loop
    print("\n[3/4] Running Scheduling & Simulation...")
    strategies = config.get("scheduler", {}).get("strategies", [
        "uniform", "empirical", "invfreq", "pt-rank", 
        "prioritized_replay", "curriculum", "power_law", "levy", "gaussian", "dro_risk_weighting", "focal_loss"
    ])
    
    agent = training_agent.TrainingAgent(result_dir=args.output_dir)
    
    if not args.dry_run:
        all_results = agent.run_simulation(strategies=strategies, n_seeds=n_seeds)
    else:
        print("Dry run enabled. Skipping simulation.")
        return
        
    # 4. Statistical Analysis & Save Results
    print("\n[4/4] Statistical Analysis & Saving Results...")
    
    summary_data = []
    
    # Reference pt-rank for paired t-test
    baseline_sr = {}
    if "uniform" in all_results:
        baseline_sr["uniform"] = [np.mean(list(run["final_success_rates"].values())) for run in all_results["uniform"]]
    
    for strategy, runs in all_results.items():
        # Calculate overall success rate for each seed
        seed_srs = []
        for run in runs:
            seed_srs.append(np.mean(list(run["final_success_rates"].values())))
            
        mean_sr = np.mean(seed_srs)
        std_sr = np.std(seed_srs)
        ci_95 = 1.96 * std_sr / np.sqrt(len(seed_srs))
        
        # Bootstrap CI
        bootstrap_means = [np.mean(np.random.choice(seed_srs, size=len(seed_srs), replace=True)) for _ in range(1000)]
        boot_ci_lower = np.percentile(bootstrap_means, 2.5)
        boot_ci_upper = np.percentile(bootstrap_means, 97.5)
        
        # Paired t-test vs uniform (if available and not uniform itself)
        p_value = 1.0
        if strategy != "uniform" and "uniform" in baseline_sr:
            try:
                _, p_value = stats.ttest_rel(seed_srs, baseline_sr["uniform"])
            except:
                p_value = 1.0
                
        summary_data.append({
            "strategy": strategy,
            "mean_sr": mean_sr,
            "std_sr": std_sr,
            "ci_95": ci_95,
            "boot_ci_lower": boot_ci_lower,
            "boot_ci_upper": boot_ci_upper,
            "p_value_vs_uniform": p_value,
            "seed_count": n_seeds,
            "mode": "simulated",
            "budget": "100k_steps",
            "timestamp": pd.Timestamp.now().isoformat(),
            "commit_hash": get_git_revision_hash(),
            "config_hash": hash(json.dumps(config, sort_keys=True))
        })
        
    df = pd.DataFrame(summary_data)
    df.to_csv(os.path.join(args.output_dir, "summary.csv"), index=False)
    
    # Generate experiment_results.json for the frontend
    frontend_data = {"metrics": {}}
    for strategy, runs in all_results.items():
        # Calculate specific metrics needed by frontend
        # Categorize tasks
        head_tasks = ["reach-v2", "push-v2", "pick-place-v2", "door-open-v2"]
        tail_tasks = ["window-open-v2", "sweep-v2", "basketball-v2"]
        
        all_srs = [np.mean(list(r["final_success_rates"].values())) for r in runs]
        overall_sr = np.mean(all_srs)
        
        # Calculate mean over seeds for each task, then avg over category
        head_srs = [np.mean([r["final_success_rates"][t] for t in head_tasks]) for r in runs]
        tail_srs = [np.mean([r["final_success_rates"][t] for t in tail_tasks]) for r in runs]
        head_sr = np.mean(head_srs)
        tail_sr = np.mean(tail_srs)
        
        # Calculate CVaR
        # CVaR@20 is the average of the lowest 20% of task success rates across seeds
        cvar_20s = []
        cvar_50s = []
        for r in runs:
            sorted_srs = np.sort(list(r["final_success_rates"].values()))
            cvar_20s.append(np.mean(sorted_srs[:max(1, int(len(sorted_srs)*0.2))]))
            cvar_50s.append(np.mean(sorted_srs[:max(1, int(len(sorted_srs)*0.5))]))
            
        frontend_data["metrics"][strategy] = {
            "overall": float(overall_sr * 100),
            "head_sr": float(head_sr * 100),
            "tail_sr": float(tail_sr * 100),
            "cvar20": float(np.mean(cvar_20s) * 100),
            "cvar50": float(np.mean(cvar_50s) * 100),
            "mode": "simulated"
        }
        
    with open(os.path.join(args.output_dir, "experiment_results.json"), "w") as f:
        json.dump(frontend_data, f, indent=4)
        
    print(f"Summary saved to {os.path.join(args.output_dir, 'summary.csv')}")
    print("\n[Pipeline Complete] Results are simulated baselines.")
