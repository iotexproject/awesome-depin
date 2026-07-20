"""
评估指标 (Evaluation Metrics)

根据文档要求的核心评估指标:
1. Head Success: 头部任务成功率
2. Tail Success: 尾部任务成功率
3. Overall: 总体成功率
4. CVaR@α: 条件风险价值 (α分位数以下的期望收益)
5. Rare Failure Recall: 稀有失败召回率
6. Sample Efficiency: 样本效率
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class EvalResult:
    """评估结果"""
    head_success: float
    tail_success: float
    overall: float
    cvar_20: float      # CVaR@20%
    rare_failure_recall: float
    per_task_success: Dict[str, float]
    training_curves: Optional[Dict] = None


class EvaluationMetrics:
    """评估指标计算器"""

    def __init__(self):
        self.history: List[Dict] = []

    def compute_head_success(self, per_task_success: Dict[str, float],
                             head_tasks: List[str]) -> float:
        """计算头部任务平均成功率"""
        if not head_tasks:
            return 0.0
        scores = [per_task_success.get(t, 0.0) for t in head_tasks]
        return np.mean(scores)

    def compute_tail_success(self, per_task_success: Dict[str, float],
                             tail_tasks: List[str]) -> float:
        """计算尾部任务平均成功率"""
        if not tail_tasks:
            return 0.0
        scores = [per_task_success.get(t, 0.0) for t in tail_tasks]
        return np.mean(scores)

    def compute_overall(self, per_task_success: Dict[str, float]) -> float:
        """计算总体平均成功率"""
        if not per_task_success:
            return 0.0
        return np.mean(list(per_task_success.values()))

    def compute_cvar(self, returns: np.ndarray, alpha: float = 0.2) -> float:
        """计算CVaR@α (条件风险价值)

        CVaR@α = E[R | R ≤ VaR_α]
        即最差α比例的期望收益

        Args:
            returns: 收益序列
            alpha: 分位数 (0.2 = 最差20%)

        Returns:
            CVaR值
        """
        if len(returns) == 0:
            return 0.0

        sorted_returns = np.sort(returns)
        cutoff = max(1, int(np.ceil(alpha * len(sorted_returns))))
        worst_returns = sorted_returns[:cutoff]

        return np.mean(worst_returns)

    def compute_rare_failure_recall(self, per_task_success: Dict[str, float],
                                     tail_tasks: List[str],
                                     threshold: float = 0.1) -> float:
        """计算稀有失败召回率

        在尾部任务中，成功率低于阈值的比例
        高recall表示能正确识别并覆盖失败模式
        """
        if not tail_tasks:
            return 0.0

        failed = sum(1 for t in tail_tasks if per_task_success.get(t, 1.0) < threshold)
        return failed / len(tail_tasks)

    def compute_sample_efficiency(self, success_curve: np.ndarray,
                                   target: float = 0.8) -> int:
        """计算样本效率: 达到目标成功率所需的步数

        Args:
            success_curve: 累积成功率曲线
            target: 目标成功率阈值

        Returns:
            达到目标的步数 (未达到则返回-1)
        """
        above = np.where(success_curve >= target)[0]
        if len(above) > 0:
            return above[0] + 1
        return -1

    def evaluate(self, per_task_success: Dict[str, float],
                 head_tasks: List[str],
                 tail_tasks: List[str],
                 episode_returns: Optional[np.ndarray] = None) -> EvalResult:
        """完整评估

        Args:
            per_task_success: 每个任务的成功率
            head_tasks: 头部任务名列表
            tail_tasks: 尾部任务名列表
            episode_returns: episode收益序列 (用于CVaR)

        Returns:
            EvalResult
        """
        head_s = self.compute_head_success(per_task_success, head_tasks)
        tail_s = self.compute_tail_success(per_task_success, tail_tasks)
        overall = self.compute_overall(per_task_success)

        # CVaR计算
        if episode_returns is not None and len(episode_returns) > 0:
            cvar = self.compute_cvar(episode_returns, alpha=0.2)
        else:
            # 从per_task_success估算
            success_values = np.array(list(per_task_success.values()))
            cvar = self.compute_cvar(success_values, alpha=0.2)

        # Rare failure recall
        rfr = self.compute_rare_failure_recall(per_task_success, tail_tasks)

        result = EvalResult(
            head_success=head_s,
            tail_success=tail_s,
            overall=overall,
            cvar_20=cvar,
            rare_failure_recall=rfr,
            per_task_success=per_task_success,
        )

        self.history.append({
            "head_success": head_s,
            "tail_success": tail_s,
            "overall": overall,
            "cvar_20": cvar,
            "rare_failure_recall": rfr,
        })

        return result

    def format_result(self, result: EvalResult, strategy_name: str = "") -> str:
        """格式化输出评估结果"""
        lines = [
            f"=== Evaluation Result {strategy_name} ===",
            f"  Head Success:    {result.head_success:.4f}",
            f"  Tail Success:    {result.tail_success:.4f}",
            f"  Overall:         {result.overall:.4f}",
            f"  CVaR@20%:        {result.cvar_20:.4f}",
            f"  Rare Fail Recall:{result.rare_failure_recall:.4f}",
            "",
            "Per-Task Success:",
        ]
        for task, score in sorted(result.per_task_success.items()):
            lines.append(f"    {task:30s}: {score:.4f}")

        return "\n".join(lines)
