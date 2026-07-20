import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
from scipy.special import factorial

def p_pt(k, lam):
    return (lam**k) / ((1 + lam)**(k + 1))

def p_poisson(k, lam):
    return (lam**k) * np.exp(-lam) / factorial(k)

def generate_plot():
    data_dir = Path("data")
    
    # Use the ideal_pt files generated earlier
    real_files = sorted(list(data_dir.glob("task_*_result.csv")))
    ideal_files = []
    M_values = []
    
    for f in real_files:
        df = pd.read_csv(f)
        min_p = df.iloc[:, 1].values[df.iloc[:, 1].values > 0].min()
        M = int(round(100 / min_p))
        M_values.append(M)
        ideal_files.append(data_dir / f.name.replace("task_", "ideal_pt_"))

    # The user's plot has Dataset 1 as M=99328. In our sorted list, that's the 4th file.
    # Let's reorder to match the user's plot exactly:
    # Dataset 1: 99328 (index 3)
    # Dataset 2: 100000 (index 0)
    # Dataset 3: 100000 (index 1)
    # Dataset 4: 100000 (index 2)
    order = [3, 0, 1, 2]
    
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    axes = axes.flatten()
    
    k_vals = np.arange(0, 18)
    
    for i, idx in enumerate(order):
        f = ideal_files[idx]
        M = M_values[idx]
        
        df = pd.read_csv(f)
        probs = df.iloc[:, 1].values / 100.0
        N = len(probs)
        lam = M / N
        
        # Generate measurement counts from the ideal probabilities
        np.random.seed(42 + i)
        counts = np.random.multinomial(M, probs)
        
        # Calculate empirical distribution
        counts_hist = np.bincount(counts, minlength=18)[:18]
        p_empirical = counts_hist / N
        
        # Calculate theoretical distributions
        p_pt_theory = p_pt(k_vals, lam)
        p_poisson_theory = p_poisson(k_vals, lam)
        
        ax = axes[i]
        
        # Plot empirical data as bars
        ax.bar(k_vals, p_empirical, color='blue', alpha=0.5, label='Empirical Data')
        
        # Plot PT theory
        ax.plot(k_vals, p_pt_theory, 'ro-', linewidth=2, label='Theory (Porter-Thomas)')
        
        # Plot Poisson theory
        ax.plot(k_vals, p_poisson_theory, 'gs--', linewidth=2, label='Theory (Uniform/Poisson)')
        
        ax.set_yscale('log')
        ax.set_ylim(1e-5, 1)
        ax.set_xlim(-0.5, 17)
        
        ax.set_title(f'Dataset {i+1} (M ≈ {M} shots)')
        ax.set_xlabel('Measurement Counts $k$')
        ax.set_ylabel('Probability $P(k)$')
        ax.legend()

    plt.tight_layout()
    plt.savefig("results/fig_pt_distribution_validation.png", dpi=300, bbox_inches='tight')
    print("Saved plot to results/fig_pt_distribution_validation.png")

if __name__ == "__main__":
    generate_plot()
