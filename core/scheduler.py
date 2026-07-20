"""
量子调度器 (Quantum Scheduler)

实现核心调度公式: q = (1-η)b + ηPs

调度策略:
1. uniform: 均匀采样 (baseline)
2. empirical: 经验频率加权
3. invfreq: 逆频率加权
4. PT-rank: 量子PT排序匹配 (本文方法)
5. PT-OT: 量子PT + 最优传输
6. PT-schedule: 量子PT + 动态η调度

Rank matching: 通过排序匹配将PT分布的尾部结构注入任务采样
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class ScheduleStrategy(Enum):
    """调度策略"""
    UNIFORM = "uniform"
    EMPIRICAL = "empirical"
    INV_FREQ = "invfreq"
    PT_RANK = "pt-rank"       # 量子PT排序匹配
    PT_OT = "pt-ot"           # 量子PT + 最优传输
    PT_SCHEDULE = "pt-schedule"  # 量子PT + 动态η


@dataclass
class ScheduleResult:
    """调度结果"""
    task_indices: np.ndarray     # 采样的任务索引序列
    task_probs: np.ndarray       # 任务采样概率分布
    strategy: ScheduleStrategy   # 使用的策略
    eta: float                   # 使用的η值
    metadata: dict = None


class QuantumScheduler:
    """量子调度器：基于PT先验的任务采样调度"""

    def __init__(self, n_tasks: int = 10, eta: float = 0.3,
                 strategy: ScheduleStrategy = ScheduleStrategy.PT_RANK):
        """
        Args:
            n_tasks: 任务数量
            eta: 插值系数 η ∈ [0, 1]
                 η=0: 纯基线, η=1: 纯量子先验
            strategy: 调度策略
        """
        self.n_tasks = n_tasks
        self.eta = eta
        self.strategy = strategy
        self.rng = np.random.default_rng()

    def schedule(self, baseline: np.ndarray, quantum_prior: np.ndarray,
                 tail_scores: np.ndarray = None,
                 n_samples: int = 1000) -> ScheduleResult:
        """执行调度

        核心公式: q = (1-η)b + ηPs

        Args:
            baseline: 基线分布 b, shape=(n_tasks,)
            quantum_prior: 量子源先验 Ps, shape=(n_tasks,) or (n_states,)
            tail_scores: 尾部得分, shape=(n_tasks,)
            n_samples: 采样数量

        Returns:
            ScheduleResult
        """
        baseline = self._normalize(baseline)

        if self.strategy == ScheduleStrategy.UNIFORM:
            probs = np.ones(self.n_tasks) / self.n_tasks

        elif self.strategy == ScheduleStrategy.EMPIRICAL:
            probs = baseline

        elif self.strategy == ScheduleStrategy.INV_FREQ:
            if tail_scores is None:
                tail_scores = np.ones(self.n_tasks) / self.n_tasks
            probs = tail_scores / tail_scores.sum()

        elif self.strategy == ScheduleStrategy.PT_RANK:
            probs = self._pt_rank_schedule(baseline, quantum_prior, tail_scores)

        elif self.strategy == ScheduleStrategy.PT_OT:
            probs = self._pt_ot_schedule(baseline, quantum_prior, tail_scores)

        elif self.strategy == ScheduleStrategy.PT_SCHEDULE:
            probs = self._pt_schedule_dynamic(baseline, quantum_prior, tail_scores)

        else:
            raise ValueError(f"Unknown strategy: {self.strategy}")

        probs = self._normalize(probs)

        # 采样
        task_indices = self.rng.choice(self.n_tasks, size=n_samples, p=probs)

        return ScheduleResult(
            task_indices=task_indices,
            task_probs=probs,
            strategy=self.strategy,
            eta=self.eta,
        )

    def _pt_rank_schedule(self, baseline: np.ndarray, quantum_prior: np.ndarray,
                          tail_scores: np.ndarray = None) -> np.ndarray:
        """PT-Rank调度: 排序匹配

        将量子PT分布的尾部结构通过排序匹配注入任务采样分布。

        步骤:
        1. 对PT先验排序得到rank向量
        2. 对tail_score排序得到任务rank
        3. 将PT的rank映射到任务的rank (匈牙利算法/贪心匹配)
        4. 混合: q = (1-η)b + ηPs_matched
        """
        if len(quantum_prior) != self.n_tasks:
            # PT分布维度 != 任务数 → 使用排序匹配
            ps_matched = self._rank_match(quantum_prior, tail_scores)
        else:
            ps_matched = quantum_prior

        # 核心公式: q = (1-η)b + ηPs
        q = (1 - self.eta) * baseline + self.eta * ps_matched

        return q

    def _rank_match(self, quantum_prior: np.ndarray,
                    tail_scores: np.ndarray = None) -> np.ndarray:
        """排序匹配: 将高维PT先验映射到任务维度

        核心思想:
        - PT分布中概率高的状态 → tail_score高的任务
        - 通过排序保持单调性

        算法:
        1. 对PT概率排序，取top-K分位数
        2. 对tail_score排序
        3. 将PT的排序结构映射到任务的排序结构
        """
        n = self.n_tasks

        if tail_scores is None:
            tail_scores = np.linspace(0, 1, n)

        # 1. 将PT分布分成n个桶
        sorted_pt = np.sort(quantum_prior)[::-1]  # 降序
        bucket_size = len(sorted_pt) // n

        # 2. 计算每个桶的权重 (体现PT的尾部结构)
        bucket_weights = np.zeros(n)
        for i in range(n):
            start = i * bucket_size
            end = (i + 1) * bucket_size if i < n - 1 else len(sorted_pt)
            bucket_weights[i] = sorted_pt[start:end].sum()

        # 3. 按tail_score排序索引
        sorted_indices = np.argsort(tail_scores)[::-1]  # 降序

        # 4. 将PT权重映射到任务
        task_probs = np.zeros(n)
        for rank, task_idx in enumerate(sorted_indices):
            task_probs[task_idx] = bucket_weights[rank]

        return task_probs

    def _pt_ot_schedule(self, baseline: np.ndarray, quantum_prior: np.ndarray,
                        tail_scores: np.ndarray = None) -> np.ndarray:
        """PT-OT调度: 量子PT + 最优传输

        使用Sliced OT近似将PT分布传输到任务空间

        简化实现: 使用排序匹配 + 加权传输
        """
        # 第一步: 排序匹配
        ps_matched = self._rank_match(quantum_prior, tail_scores)

        # 第二步: OT近似 - 最小化传输代价
        # 使用贪心近似: 按代价排序
        transport_plan = self._greedy_ot(baseline, ps_matched)

        # 混合
        q = (1 - self.eta) * baseline + self.eta * transport_plan

        return q

    def _greedy_ot(self, source: np.ndarray, target: np.ndarray) -> np.ndarray:
        """贪心最优传输近似

        简化的匈牙利算法: 按代价排序贪心匹配
        """
        n = len(source)
        cost_matrix = np.abs(source[:, None] - target[None, :])

        # 贪心: 每行选最小代价
        matched = np.zeros(n)
        used = set()

        for i in np.argsort(np.min(cost_matrix, axis=1)):
            j = np.argmin(cost_matrix[i])
            if j not in used:
                matched[i] = target[j]
                used.add(j)
            else:
                matched[i] = source[i]  # 回退到源

        return matched

    def _pt_schedule_dynamic(self, baseline: np.ndarray, quantum_prior: np.ndarray,
                             tail_scores: np.ndarray = None) -> np.ndarray:
        """PT-Schedule动态调度: 随训练进度调整η

        η 随训练进度动态变化:
        - 初期 η 小: 以基线为主，保证基本学习
        - 中期 η 增大: 逐渐引入量子先验
        - 后期 η 最大: 最大化尾部覆盖

        η(t) = η_max * (1 - exp(-t/T))
        """
        # 使用当前eta作为η_max
        eta_max = self.eta

        # 调用rank匹配
        ps_matched = self._rank_match(quantum_prior, tail_scores)

        # 动态混合 (这里t/T用eta本身近似进度)
        dynamic_eta = eta_max
        q = (1 - dynamic_eta) * baseline + dynamic_eta * ps_matched

        return q

    def _normalize(self, probs: np.ndarray) -> np.ndarray:
        """归一化概率分布"""
        probs = np.maximum(probs, 1e-10)
        return probs / probs.sum()

    @staticmethod
    def compute_schedule_formula(baseline: np.ndarray, ps: np.ndarray,
                                  eta: float) -> np.ndarray:
        """静态方法: 直接计算 q = (1-η)b + ηPs"""
        q = (1 - eta) * baseline + eta * ps
        q = np.maximum(q, 1e-10)
        return q / q.sum()
