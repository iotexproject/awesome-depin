import os
import json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from typing import Dict, Any
from core.quantum_prior import QuantumPriorEngine

class QuantumSourceAgent:
    """
    Quantum Source Agent: Reads quantum CSV data, normalizes it, calculates statistics, 
    and provides a default prior distribution for the scheduler.
    """
    def __init__(self):
        self.priors: Dict[str, np.ndarray] = {}
        self.summary: Dict[str, Any] = {}
        self.default_prior_name: str = None
        self.default_prior: np.ndarray = None
        self.engine = QuantumPriorEngine()

    def load_quantum_prior(self, data_dir: str) -> Dict[str, Any]:
        """
        1. 递归扫描 data/ 下所有 CSV 文件
        2. 自动识别概率列或计数列
        3. 统一归一化为概率向量 p
        4. 计算基础统计量并保存拟合图
        5. 输出一个标准 source prior 文件
        6. 选择一份“默认量子源分布”供后续 scheduler 使用
        """
        csv_files = []
        for root, _, files in os.walk(data_dir):
            for file in files:
                if file.endswith(".csv"):
                    csv_files.append(os.path.join(root, file))
        
        os.makedirs("results", exist_ok=True)
        
        for file in csv_files:
            try:
                df = pd.read_csv(file)
                
                # 自动识别概率列或计数列
                target_col = None
                for col in df.columns:
                    col_lower = col.lower()
                    if any(k in col_lower for k in ["prob", "count", "freq", "rate", "val"]):
                        if pd.api.types.is_numeric_dtype(df[col]):
                            target_col = col
                            break
                
                if target_col is None:
                    for col in df.columns[1:]:
                        if pd.api.types.is_numeric_dtype(df[col]):
                            target_col = col
                            break
                            
                if target_col is None:
                    for col in df.columns:
                        if pd.api.types.is_numeric_dtype(df[col]):
                            target_col = col
                            break

                if target_col is None:
                    print(f"[QuantumSourceAgent] Warning: Could not identify numeric column in {file}")
                    continue

                raw_values = df[target_col].dropna().values
                raw_values = raw_values[raw_values >= 0]
                
                if len(raw_values) == 0 or raw_values.sum() == 0:
                    continue

                p = raw_values / raw_values.sum()
                
                # Try to extract shots and qubits if available
                shots = None
                if "count" in target_col.lower():
                    shots = int(raw_values.sum())
                    
                # Use QuantumPriorEngine to compute statistics
                stats = self.engine._compute_statistics(p, shots=shots)
                
                name = os.path.basename(file)
                self.priors[name] = p
                self.summary[name] = stats
                
                # Plot and save Exp(1)/PT fit
                self._plot_fit(p, name)
                
            except Exception as e:
                print(f"[QuantumSourceAgent] Error processing {file}: {e}")

        # Choose the first prior as default
        if len(self.priors) > 0:
            self.default_prior_name = list(self.priors.keys())[0]
            self.default_prior = self.priors[self.default_prior_name]
            print(f"[QuantumSourceAgent] Loaded {len(self.priors)} prior(s). Default: {self.default_prior_name}")
        else:
            print("[QuantumSourceAgent] No valid quantum priors found. Using uniform fallback.")
            self.default_prior_name = "uniform_fallback"
            self.default_prior = np.ones(1024) / 1024
            self.priors["uniform_fallback"] = self.default_prior

        # Save summary to JSON
        with open("results/quantum_source_summary.json", "w") as f:
            json.dump(self.summary, f, indent=4)
        
        return self.summary
        
    def _plot_fit(self, p: np.ndarray, name: str):
        """Plot the empirical distribution against Exp(1) ideal PT distribution"""
        plt.figure(figsize=(8, 6))
        n = len(p)
        scaled_p = p * n
        plt.hist(scaled_p, bins=50, density=True, alpha=0.6, color='b', label=r'Empirical $N \cdot p_x$')
        
        x = np.linspace(0, max(scaled_p.max(), 5), 100)
        plt.plot(x, np.exp(-x), 'r-', lw=2, label='Ideal Exp(1)')
        
        plt.title(f'Porter-Thomas Fit: {name}')
        plt.xlabel(r'$N \cdot p_x$')
        plt.ylabel('Density')
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.savefig(f"results/{name}_pt_fit.png")
        plt.close()

    def get_scheduler_prior(self) -> np.ndarray:
        return self.default_prior

_agent_instance = QuantumSourceAgent()

def load_quantum_prior(data_dir: str = "data/quantum_runs") -> Dict[str, Any]:
    return _agent_instance.load_quantum_prior(data_dir)

def get_scheduler_prior() -> np.ndarray:
    return _agent_instance.get_scheduler_prior()

if __name__ == "__main__":
    # Test execution
    summary = load_quantum_prior("data")
    prior = get_scheduler_prior()
    print(f"Default prior shape: {prior.shape}, sum: {prior.sum()}")
