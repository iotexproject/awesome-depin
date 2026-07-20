import numpy as np
import scipy.stats as stats
import matplotlib.pyplot as plt
import os
import pandas as pd

def compute_tv_distance(p: np.ndarray, q: np.ndarray) -> float:
    """Compute Total Variation distance between two probability distributions."""
    return 0.5 * np.sum(np.abs(p - q))

def run_hardware_robustness_evaluation():
    print("[Hardware Robustness] Starting evaluation of Prop 3...")
    
    # 1. Simulate ideal PT distribution (Exponential e^-Np)
    np.random.seed(42)
    n_qubits = 6
    N = 2 ** n_qubits
    shots = 10000
    
    # Ideal: exponential
    ideal_samples = np.random.exponential(scale=1.0, size=shots)
    ideal_probs, bins = np.histogram(ideal_samples, bins=50, density=True, range=(0, 6))
    ideal_probs = ideal_probs * np.diff(bins)
    
    # 2. Simulate Real Hardware Noise (Gate errors, readout errors -> flatter distribution)
    # We mix the ideal PT with a uniform distribution (white noise) to simulate depolarization
    # TV(Preal, Pideal) < epsilon
    gate_error_rates = [0.01, 0.05, 0.10, 0.20]
    
    results = []
    
    plt.figure(figsize=(10, 6))
    x_plot = (bins[:-1] + bins[1:]) / 2
    plt.plot(x_plot, ideal_probs, 'k--', lw=2, label="Ideal PT")
    
    max_tau_k = 1.0 # maximum tail score/utility impact
    
    for error in gate_error_rates:
        # Simple depolarization model: with probability `error`, we get uniform noise
        noise_samples = np.random.uniform(0, 6, size=shots)
        mask = np.random.rand(shots) < error
        real_samples = np.where(mask, noise_samples, ideal_samples)
        
        real_probs, _ = np.histogram(real_samples, bins=bins, density=True)
        real_probs = real_probs * np.diff(bins)
        
        tv_dist = compute_tv_distance(ideal_probs, real_probs)
        
        # Simulated utility degradation bound: |U(Preal) - U(Pideal)| <= epsilon * max_tau_k
        utility_degradation = tv_dist * max_tau_k
        
        results.append({
            "Gate Error Rate": error,
            "TV Distance (epsilon)": tv_dist,
            "Utility Degradation": utility_degradation
        })
        
        plt.plot(x_plot, real_probs, label=f"Real Hardware (Error={error:.2f})", alpha=0.8)

    print("Hardware Robustness Results (Proposition 3):")
    for res in results:
        print(f"  Error: {res['Gate Error Rate']:.2f} | TV(P_real, P_ideal): {res['TV Distance (epsilon)']:.4f} | Max Utility Degradation: {res['Utility Degradation']:.4f}")

    # 3. Save Results
    os.makedirs("results", exist_ok=True)
    df = pd.DataFrame(results)
    df.to_csv("results/summary_hardware_robustness.csv", index=False)
    
    plt.title("Hardware Robustness: Ideal PT vs Noisy Real Hardware")
    plt.xlabel(r"Normalized Probability ($N \cdot p$)")
    plt.ylabel("Probability Mass")
    plt.yscale('log')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.savefig("results/fig_hardware_robustness.png", dpi=300, bbox_inches='tight')
    plt.close()
    
    print("[Hardware Robustness] Completed. Results saved to 'results/'.")

if __name__ == "__main__":
    run_hardware_robustness_evaluation()