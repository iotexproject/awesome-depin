import numpy as np
import scipy.stats as stats
import matplotlib.pyplot as plt
import os
import json
import pandas as pd
from agents.quantum_transport_agent import pt_ot_mapping, MixtureDistribution

def run_risk_evaluation():
    print("[Evaluate Risk Scene] Starting evaluation of Mapping II...")
    
    # 1. Define target risk law (Beta mixture)
    # H = (1-rho) Beta(a1, b1) + rho Beta(a2, b2)
    rho = 0.1
    dist_head = stats.beta(2, 5)   # low-noise head
    dist_tail = stats.beta(5, 2)   # high-noise tail
    scale = 1.0
    
    target_dist = MixtureDistribution(rho, dist_head, dist_tail, scale=scale)
    
    # 2. Simulate PT source samples (exponential distribution)
    np.random.seed(42)
    n_samples = 10000
    source_samples = np.random.exponential(scale=1.0, size=n_samples)
    
    # 3. Generate risk scenes using different strategies
    # a) Uniform
    risk_uniform = np.random.uniform(0, scale, size=n_samples)
    
    # b) Clipped Gaussian
    risk_gaussian = np.clip(np.random.normal(loc=0.3, scale=0.2, size=n_samples), 0, scale)
    
    # c) Linear Scaling of PT
    risk_linear = np.clip(source_samples / np.max(source_samples) * scale, 0, scale)
    
    # d) PT-OT Quantile Transport
    risk_pt_ot = pt_ot_mapping(source_samples, target_dist.ppf)
    
    # Generate true samples from target for distance calculation
    # Sample from mixture
    choices = np.random.rand(n_samples) < rho
    target_samples = np.where(choices, dist_tail.rvs(n_samples), dist_head.rvs(n_samples)) * scale
    
    # 4. Calculate Wasserstein-1 distance
    w1_uniform = stats.wasserstein_distance(risk_uniform, target_samples)
    w1_gaussian = stats.wasserstein_distance(risk_gaussian, target_samples)
    w1_linear = stats.wasserstein_distance(risk_linear, target_samples)
    w1_pt_ot = stats.wasserstein_distance(risk_pt_ot, target_samples)
    
    print(f"Wasserstein-1 Distances to Target Law:")
    print(f"  Uniform:         {w1_uniform:.4f}")
    print(f"  Gaussian:        {w1_gaussian:.4f}")
    print(f"  Linear Scaling:  {w1_linear:.4f}")
    print(f"  PT-OT (Ours):    {w1_pt_ot:.4f}")
    
    # 5. Save Results to CSV
    os.makedirs("results", exist_ok=True)
    summary_data = [
        {"Generator": "Uniform", "Wasserstein_1": w1_uniform},
        {"Generator": "Gaussian", "Wasserstein_1": w1_gaussian},
        {"Generator": "Linear Scaling", "Wasserstein_1": w1_linear},
        {"Generator": "PT-OT", "Wasserstein_1": w1_pt_ot}
    ]
    df = pd.DataFrame(summary_data)
    df.to_csv("results/summary_risk.csv", index=False)
    
    # 6. Plot distributions
    plt.figure(figsize=(10, 6))
    
    # True target PDF
    x = np.linspace(0, scale, 1000)
    pdf_target = target_dist.cdf(x + 1e-4) - target_dist.cdf(x) # numeric derivative
    pdf_target /= 1e-4
    plt.plot(x, pdf_target, 'k--', lw=2, label="Target Density")
    
    # Plot KDEs
    import seaborn as sns
    sns.kdeplot(risk_gaussian, label="Gaussian", color="gray", linestyle=":")
    sns.kdeplot(risk_linear, label="Linear Scaling", color="orange", linestyle="-.")
    sns.kdeplot(risk_pt_ot, label="PT-OT", color="blue", lw=2)
    
    plt.title("Risk Scene Distribution Matching (Mapping II)")
    plt.xlabel("Perturbation Severity")
    plt.ylabel("Density")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.savefig("results/fig_risk_wasserstein.png", dpi=300, bbox_inches='tight')
    plt.close()
    print("[Evaluate Risk Scene] Completed. Results saved to 'results/' directory.")

if __name__ == "__main__":
    run_risk_evaluation()
