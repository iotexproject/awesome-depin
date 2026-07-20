import os
import argparse
import importlib

def main():
    parser = argparse.ArgumentParser(description="Q-TAIL-MVP Orchestrator")
    parser.add_argument("--mode", type=str, default="simulation", choices=["simulation", "real", "hardware_robustness", "mt50_sim", "exploration_noise", "risk_scene", "ablation"], help="Execution mode")
    parser.add_argument("--config", type=str, default="config/default.yaml", help="Path to config file")
    parser.add_argument("--seed", type=int, default=2026, help="Global random seed")
    parser.add_argument("--output_dir", type=str, default="results", help="Output directory")
    parser.add_argument("--dry-run", action="store_true", help="Dry run mode without full execution")
    parser.add_argument("--resume", action="store_true", help="Resume from previous checkpoint")
    
    args = parser.parse_args()
    
    print("="*60)
    print(f" Q-TAIL-MVP Orchestrator [{args.mode.upper()}]")
    print("="*60)
    
    os.makedirs(args.output_dir, exist_ok=True)
    
    # Dispatch to specific experiment based on mode
    if args.mode == "simulation":
        exp_module = importlib.import_module("experiments.mt10_sim")
        exp_module.run(args)
    elif args.mode == "real":
        exp_module = importlib.import_module("experiments.mt10_real")
        exp_module.run(args)
    elif args.mode == "mt50_sim":
        exp_module = importlib.import_module("experiments.mt50_sim")
        exp_module.run(args)
    elif args.mode == "risk_scene":
        exp_module = importlib.import_module("experiments.risk_scene")
        exp_module.run(args)
    elif args.mode == "exploration_noise":
        exp_module = importlib.import_module("experiments.exploration_noise")
        exp_module.run(args)
    elif args.mode == "hardware_robustness":
        exp_module = importlib.import_module("experiments.hardware_robustness")
        exp_module.run(args)
    elif args.mode == "ablation":
        exp_module = importlib.import_module("experiments.ablation")
        exp_module.run(args)
    else:
        print(f"Unknown mode: {args.mode}")

if __name__ == "__main__":
    main()