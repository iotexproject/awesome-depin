import numpy as np
import pandas as pd
from pathlib import Path
from scipy import stats

def compute_metrics(probs, filename):
    n = len(probs)
    mean_val = np.mean(probs)
    std_val = np.std(probs)
    cv = std_val / mean_val if mean_val > 0 else 0

    # KS test vs Exp(1)
    scaled = probs * n
    ks_stat, ks_pvalue = stats.kstest(scaled, 'expon', args=(0, 1))

    # Heavy tail ratio: P(x > 2*mean)
    heavy_ratio = np.mean(probs > 2 * mean_val)

    # Linear XEB (Shape Proxy)
    # F_XEB = N * sum(p_i^2) - 1
    xeb_shape = n * np.sum(probs**2) - 1
    
    # Ideal PT distribution for KL divergence
    ideal_probs = np.zeros(n)
    if n > 0:
        for i in range(1, n + 1):
            ideal_probs[i-1] = -np.log(1.0 - (i - 0.5)/n) / n
        ideal_probs = ideal_probs / ideal_probs.sum()
        ideal_probs_sorted = np.sort(ideal_probs)
        probs_sorted = np.sort(probs)
        kl_div = np.sum(probs_sorted * np.log((probs_sorted + 1e-12) / (ideal_probs_sorted + 1e-12)))
    else:
        kl_div = 0.0

    n_qubits = int(np.log2(n)) if n > 0 else 0
    shots = 100000 
    
    return {
        "File / Experiment": filename,
        "Qubits": n_qubits,
        "Layers/Depth": 28,
        "2-Qubit Gates": "N/A",
        "Sampling Shots": shots,
        "CV (Coefficient of Variation)": cv,
        "KS Statistic": ks_stat,
        "KL Divergence": kl_div,
        "Heavy Tail Ratio": heavy_ratio,
        "F_XEB (Shape Proxy)": xeb_shape,
        "F_XEB (Strict Linear)": "N/A (Requires Circuit)"
    }

data_dir = Path("data")
real_files = sorted(list(data_dir.glob("task_*_result.csv")))
ideal_files = sorted(list(data_dir.glob("ideal_pt_*_result.csv")))

results = []

for f in real_files:
    df = pd.read_csv(f)
    probs = df.iloc[:, 1].values.astype(float)
    probs = probs / probs.sum() # Normalize
    metrics = compute_metrics(probs, "Real: " + f.name)
    results.append(metrics)

for f in ideal_files:
    df = pd.read_csv(f)
    probs = df.iloc[:, 1].values.astype(float)
    probs = probs / probs.sum() # Normalize
    metrics = compute_metrics(probs, "Ideal: " + f.name)
    results.append(metrics)

res_df = pd.DataFrame(results)

out_path = data_dir / "Ideal_vs_Real_Metrics_Comparison.xlsx"
res_df.to_excel(out_path, index=False)
print(f"Saved metrics comparison to {out_path}")
