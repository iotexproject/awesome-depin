"""
量子先验引擎 (Quantum Prior Engine)

从量子硬件CSV数据中构建Porter-Thomas源先验分布。
Porter-Thomas分布: p(x) = (N/2) * exp(-Nx/2)，等价于Exp(1)在N→∞时。

核心功能:
1. 读取量子CSV数据 (States, Raw probabilities)
2. 构建离散概率分布 Ps
3. 验证PT分布质量 (CV, KS统计量, Gini系数)
4. 讯源融合: 多次采样结果取平均
5. CDF反函数构建: u = Fpt(y), y = Fpt^{-1}(u)
"""

import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from scipy import stats


class QuantumPriorEngine:
    """量子先验引擎：从量子硬件数据构建PT源先验"""

    def __init__(self, data_dir: str = None):
        self.data_dir = Path(data_dir) if data_dir else None
        self.sources: Dict[str, dict] = {}  # 多量子源存储
        self.merged_prior: Optional[np.ndarray] = None
        self.merged_states: Optional[List[str]] = None

    def load_csv(self, csv_path: str, source_name: str = None) -> dict:
        """加载单个量子CSV数据文件

        Args:
            csv_path: CSV文件路径
            source_name: 量子源名称

        Returns:
            dict: 包含states, probabilities, statistics的字典
        """
        df = pd.read_csv(csv_path)
        # 处理列名: "States" / " Raw probabilities(%)"
        states = df.iloc[:, 0].values.astype(str)
        probs = df.iloc[:, 1].values.astype(float)

        # 归一化概率 (确保和为1)
        probs = probs / probs.sum()

        if source_name is None:
            source_name = Path(csv_path).stem

        source_info = {
            "states": states,
            "probabilities": probs,
            "n_states": len(states),
            "n_qubits": len(states[0]) if len(states) > 0 else 0,
            "statistics": self._compute_statistics(probs),
        }

        self.sources[source_name] = source_info
        return source_info

    def load_all_csv(self, data_dir: str = None) -> Dict[str, dict]:
        """加载目录下所有量子CSV数据"""
        d = Path(data_dir) if data_dir else self.data_dir
        if d is None:
            raise ValueError("No data directory specified")

        results = {}
        for csv_file in sorted(d.glob("task_*_result.csv")):
            name = csv_file.stem
            results[name] = self.load_csv(str(csv_file), name)

        # 合并所有源
        if results:
            self._merge_sources()

        return results

    def _merge_sources(self):
        """融合多量子源: 对所有源的概率取平均"""
        if not self.sources:
            return

        # 使用第一个源的状态作为基准
        first_source = next(iter(self.sources.values()))
        self.merged_states = first_source["states"]
        n_states = first_source["n_states"]

        # 对齐并平均
        merged_probs = np.zeros(n_states)
        state_to_idx = {s: i for i, s in enumerate(self.merged_states)}

        for source in self.sources.values():
            for state, prob in zip(source["states"], source["probabilities"]):
                if state in state_to_idx:
                    merged_probs[state_to_idx[state]] += prob
                else:
                    # 新状态，扩展
                    merged_probs = np.append(merged_probs, prob)
                    self.merged_states = np.append(self.merged_states, state)

        merged_probs /= len(self.sources)
        merged_probs /= merged_probs.sum()  # 重新归一化

        self.merged_prior = merged_probs

    def _compute_statistics(self, probs: np.ndarray, n_qubits: int = None, shots: int = None) -> dict:
        """计算PT分布验证统计量
        
        验证指标:
        - Mean: 期望值 ≈ 1/N
        - CV: 变异系数 ≈ 1 (Exp(1)特征)
        - KS: Kolmogorov-Smirnov统计量 (与Exp(1)比较)
        - KL: Kullback-Leibler散度 (与PT分布)
        - TV: Total Variation Distance (与PT分布)
        - Gini: 基尼系数 (衡量不均匀度)
        - Heavy_tail_ratio: P(X > 2*E[X]) 的比例
        """
        n = len(probs)
        mean_val = np.mean(probs)
        std_val = np.std(probs)
        cv = std_val / mean_val if mean_val > 0 else 0

        # KS test vs Exp(1) scaled by N*probs
        scaled = probs * n  # 在PT假设下应近似Exp(1)
        ks_stat, ks_pvalue = stats.kstest(scaled, 'expon', args=(0, 1))
        
        # Ideal PT distribution
        # p(x) = N * exp(-Nx) for x in probs
        # Discrete PT expected sorted values: approx -ln(1 - i/N)/N
        ideal_probs = np.zeros(n)
        if n > 0:
            for i in range(1, n + 1):
                ideal_probs[i-1] = -np.log(1.0 - (i - 0.5)/n) / n
            ideal_probs = ideal_probs / ideal_probs.sum()
            ideal_probs_sorted = np.sort(ideal_probs)
            probs_sorted = np.sort(probs)
            
            # KL Divergence
            kl_div = np.sum(probs_sorted * np.log((probs_sorted + 1e-12) / (ideal_probs_sorted + 1e-12)))
            
            # Total Variation Distance
            tv_dist = 0.5 * np.sum(np.abs(probs_sorted - ideal_probs_sorted))
        else:
            kl_div = 0.0
            tv_dist = 0.0

        # Gini coefficient
        n_gini = len(probs_sorted)
        index = np.arange(1, n_gini + 1)
        gini = (2 * np.sum(index * probs_sorted) - (n_gini + 1) * np.sum(probs_sorted)) / (
            n_gini * np.sum(probs_sorted) + 1e-12
        )

        # Heavy tail ratio: P > 2*mean
        heavy_ratio = np.mean(probs > 2 * mean_val)

        # Entropy
        entropy = -np.sum(probs * np.log2(probs + 1e-30))
        
        # Top-k mass
        top_1_mass = float(probs_sorted[-1]) if n > 0 else 0.0
        top_5_mass = float(np.sum(probs_sorted[-5:])) if n >= 5 else float(np.sum(probs_sorted))
        support_size = int(np.sum(probs > 0))

        return {
            "n_qubits": n_qubits if n_qubits is not None else int(np.log2(n)) if n > 0 else 0,
            "shots": shots if shots is not None else -1,
            "support_size": support_size,
            "mean": mean_val,
            "std": std_val,
            "cv": cv,
            "ks_statistic": ks_stat,
            "ks_pvalue": ks_pvalue,
            "kl_divergence": kl_div,
            "tv_distance": tv_dist,
            "gini": gini,
            "top_1_mass": top_1_mass,
            "top_5_mass": top_5_mass,
            "heavy_tail_ratio": heavy_ratio,
            "entropy": entropy,
            "n_states": n,
        }

    def get_source_prior(self, source_name: str = None) -> Tuple[np.ndarray, List[str]]:
        """获取量子源先验分布

        Args:
            source_name: 指定源名，None则使用合并后的先验

        Returns:
            (probabilities, states)
        """
        if source_name and source_name in self.sources:
            return self.sources[source_name]["probabilities"], self.sources[source_name]["states"]

        if self.merged_prior is not None:
            return self.merged_prior, self.merged_states

        raise ValueError("No quantum prior available. Load data first.")

    def build_cdf(self, probs: np.ndarray = None) -> Tuple[np.ndarray, np.ndarray]:
        """构建CDF用于映射

        u = Fpt(y): 将概率值映射到[0,1]均匀空间

        Returns:
            (sorted_probs, cdf_values)
        """
        if probs is None:
            probs = self.merged_prior

        sorted_probs = np.sort(probs)
        cdf = np.cumsum(sorted_probs)
        cdf = cdf / cdf[-1]  # 归一化到[0,1]

        return sorted_probs, cdf

    def inverse_cdf(self, u: np.ndarray, probs: np.ndarray = None) -> np.ndarray:
        """CDF反函数: y = Fpt^{-1}(u)

        将[0,1]均匀随机数映射到PT分布空间

        Args:
            u: [0,1]均匀随机数
            probs: 概率分布 (None则使用merged_prior)

        Returns:
            对应的概率值
        """
        if probs is None:
            probs = self.merged_prior

        sorted_probs, cdf = self.build_cdf(probs)

        # 插值查找
        result = np.interp(u, cdf, sorted_probs)
        return result

    def validate_pt_hypothesis(self, probs: np.ndarray = None) -> dict:
        """完整验证Porter-Thomas假设

        根据文档要求验证:
        1. CV ≈ 1 (Exp(1)特征: mean=1, std=1, CV=1)
        2. KS统计量与Exp(1)一致
        3. Heavy tail ratio对比

        Returns:
            验证报告dict
        """
        if probs is None:
            probs = self.merged_prior
        if probs is None:
            raise ValueError("No probability distribution loaded")

        stats_dict = self._compute_statistics(probs)

        # 验证条件
        cv_ok = 0.8 < stats_dict["cv"] < 1.5
        ks_ok = stats_dict["ks_statistic"] < 0.3
        heavy_ok = stats_dict["heavy_tail_ratio"] > 0.05

        report = {
            **stats_dict,
            "cv_check": cv_ok,
            "ks_check": ks_ok,
            "heavy_tail_check": heavy_ok,
            "pt_hypothesis_accepted": cv_ok and ks_ok,
            "expected_cv": 1.0,
            "expected_heavy_tail": np.exp(-2),  # ≈ 0.135 for Exp(1)
        }

        return report
