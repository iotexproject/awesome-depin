"""
语义映射器 (Semantic Mapper)

将任务特征映射到语义桶 (semantic buckets)，用于识别长尾结构。

核心功能:
1. 任务尾部得分计算: rp = α·rarity + β·difficulty + γ·failure_rate
2. Meta-World MT10任务分类: 4 head / 3 medium / 3 tail
3. Zipf尾部结构分析
4. 语义桶: task_bucket, scene_condition, object_condition, difficulty_level
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum


class TailCategory(Enum):
    """任务尾部分类"""
    HEAD = "head"      # 高频高成功率
    MEDIUM = "medium"  # 中等
    TAIL = "tail"      # 低频低成功率 (长尾)


@dataclass
class TaskProfile:
    """任务特征档案"""
    name: str
    env_id: str
    rarity: float = 0.0       # 稀有度: 采样频率的倒数
    difficulty: float = 0.0   # 难度: 基于动作空间复杂度
    failure_rate: float = 0.0 # 失败率: 1 - success_rate
    success_rate: float = 0.0
    tail_score: float = 0.0   # 综合尾部得分
    category: TailCategory = TailCategory.MEDIUM
    metadata: dict = field(default_factory=dict)


class SemanticMapper:
    """语义映射器：任务→语义桶映射"""

    # Meta-World MT10 标准任务分类 (基于文档)
    # 头部: reach, push, pick-place (高频简单任务)
    # 中等: open drawer, close drawer (中等难度)
    # 尾部: 复杂组合操作 (低频高难度)
    MT10_TASK_CATEGORIES = {
        # Head tasks (4): 简单、高频、高成功率
        "reach-v3": TailCategory.HEAD,
        "push-v3": TailCategory.HEAD,
        "pick-place-v3": TailCategory.HEAD,
        "plate-slide-v3": TailCategory.HEAD,
        # Medium tasks (3): 中等难度
        "drawer-open-v3": TailCategory.MEDIUM,
        "drawer-close-v3": TailCategory.MEDIUM,
        "button-press-topdown-v3": TailCategory.MEDIUM,
        # Tail tasks (3): 高难度、低成功率、长尾
        "assembly-v3": TailCategory.TAIL,
        "hammer-v3": TailCategory.TAIL,
        "peg-insert-side-v3": TailCategory.TAIL,
    }

    # 完整50任务分类 (MT50)
    MT50_HEAD_TASKS = [
        "reach-v3", "push-v3", "pick-place-v3", "plate-slide-v3",
        "push-back-v3", "sweep-v3", "sweep-into-v3",
    ]
    MT50_MEDIUM_TASKS = [
        "drawer-open-v3", "drawer-close-v3", "button-press-topdown-v3",
        "button-press-v3", "dial-turn-v3", "lever-pull-v3",
        "coffee-push-v3", "coffee-pull-v3",
    ]
    MT50_TAIL_TASKS = [
        "assembly-v3", "hammer-v3", "peg-insert-side-v3",
        "bin-picking-v3", "box-close-v3", "door-close-v3",
        "door-open-v3", "door-lock-v3", "door-unlock-v3",
        "hand-insert-v3", "disassemble-v3", "peg-unplug-side-v3",
    ]

    def __init__(self, alpha: float = 1.0, beta: float = 0.6, gamma: float = 0.7):
        """
        Args:
            alpha: rarity权重
            beta: difficulty权重
            gamma: failure_rate权重
        """
        self.alpha = alpha
        self.beta = beta
        self.gamma = gamma
        self.task_profiles: Dict[str, TaskProfile] = {}

    def compute_tail_score(self, rarity: float, difficulty: float, failure_rate: float) -> float:
        """计算综合尾部得分

        rp = α·rarity + β·difficulty + γ·failure_rate

        高分表示更"尾部"（更难、更稀有、更易失败）
        """
        return self.alpha * rarity + self.beta * difficulty + self.gamma * failure_rate

    def register_task(self, name: str, env_id: str, rarity: float = 0.0,
                      difficulty: float = 0.0, success_rate: float = 0.0,
                      metadata: dict = None) -> TaskProfile:
        """注册任务到映射器"""
        failure_rate = 1.0 - success_rate
        tail_score = self.compute_tail_score(rarity, difficulty, failure_rate)

        # 自动分类
        category = self._classify_task(tail_score, env_id)

        profile = TaskProfile(
            name=name,
            env_id=env_id,
            rarity=rarity,
            difficulty=difficulty,
            failure_rate=failure_rate,
            success_rate=success_rate,
            tail_score=tail_score,
            category=category,
            metadata=metadata or {},
        )

        self.task_profiles[name] = profile
        return profile

    def _classify_task(self, tail_score: float, env_id: str = None) -> TailCategory:
        """根据尾部得分和环境ID分类任务"""
        # 优先使用预定义分类
        if env_id and env_id in self.MT10_TASK_CATEGORIES:
            return self.MT10_TASK_CATEGORIES[env_id]

        # 按得分分类
        if tail_score < 0.33:
            return TailCategory.HEAD
        elif tail_score < 0.66:
            return TailCategory.MEDIUM
        else:
            return TailCategory.TAIL

    def get_category_distribution(self) -> Dict[TailCategory, List[TaskProfile]]:
        """获取当前任务分类分布"""
        dist = {cat: [] for cat in TailCategory}
        for profile in self.task_profiles.values():
            dist[profile.category].append(profile)
        return dist

    def get_tail_scores_vector(self, task_names: List[str] = None) -> np.ndarray:
        """获取尾部得分向量 (用于调度器)"""
        if task_names is None:
            task_names = list(self.task_profiles.keys())

        scores = []
        for name in task_names:
            if name in self.task_profiles:
                scores.append(self.task_profiles[name].tail_score)
            else:
                scores.append(0.5)  # 未知任务默认中等

        return np.array(scores)

    def build_empirical_distribution(self, task_names: List[str] = None) -> np.ndarray:
        """构建经验分布 (inverse-frequency weighting)

        基于尾部得分构建采样概率:
        - 高tail_score的任务应该获得更多采样
        - 使用softmax归一化
        """
        scores = self.get_tail_scores_vector(task_names)

        # Inverse-frequency: tail任务权重更高
        weights = 1.0 / (1.0 - scores + 0.01)  # 避免除零

        # Softmax归一化
        weights = weights / weights.sum()

        return weights

    def build_invfreq_distribution(self, task_names: List[str] = None) -> np.ndarray:
        """构建逆频率分布

        完全按频率的倒数加权
        """
        scores = self.get_tail_scores_vector(task_names)

        # 逆频率: 直接使用rarity作为权重
        rarity_scores = np.array([
            self.task_profiles[name].rarity if name in self.task_profiles else 0.5
            for name in (task_names or self.task_profiles.keys())
        ])

        weights = rarity_scores + 1e-8
        weights = weights / weights.sum()

        return weights

    def auto_register_mt10(self) -> Dict[str, TaskProfile]:
        """自动注册Meta-World MT10标准任务

        基于文档中的预定义难度和成功率
        """
        mt10_profiles = {
            # Head tasks
            "reach-v3": {"rarity": 0.1, "difficulty": 0.1, "success_rate": 0.95},
            "push-v3": {"rarity": 0.1, "difficulty": 0.2, "success_rate": 0.90},
            "pick-place-v3": {"rarity": 0.15, "difficulty": 0.25, "success_rate": 0.85},
            "plate-slide-v3": {"rarity": 0.1, "difficulty": 0.15, "success_rate": 0.88},
            # Medium tasks
            "drawer-open-v3": {"rarity": 0.3, "difficulty": 0.4, "success_rate": 0.65},
            "drawer-close-v3": {"rarity": 0.3, "difficulty": 0.35, "success_rate": 0.70},
            "button-press-topdown-v3": {"rarity": 0.25, "difficulty": 0.3, "success_rate": 0.72},
            # Tail tasks
            "assembly-v3": {"rarity": 0.7, "difficulty": 0.8, "success_rate": 0.25},
            "hammer-v3": {"rarity": 0.8, "difficulty": 0.85, "success_rate": 0.15},
            "peg-insert-side-v3": {"rarity": 0.9, "difficulty": 0.9, "success_rate": 0.10},
        }

        results = {}
        for name, attrs in mt10_profiles.items():
            results[name] = self.register_task(
                name=name, env_id=name, **attrs
            )

        return results

    def get_semantic_buckets(self) -> Dict[str, List[str]]:
        """获取语义桶分类

        返回按桶分组的任务名列表
        """
        buckets = {
            "head_easy": [],       # 简单高频
            "head_standard": [],   # 标准高频
            "medium_standard": [], # 标准中等
            "medium_tricky": [],   # 棘手中等
            "tail_hard": [],       # 高难度
            "tail_rare": [],       # 稀有任务
        }

        for name, profile in self.task_profiles.items():
            if profile.category == TailCategory.HEAD:
                if profile.difficulty < 0.15:
                    buckets["head_easy"].append(name)
                else:
                    buckets["head_standard"].append(name)
            elif profile.category == TailCategory.MEDIUM:
                if profile.difficulty < 0.35:
                    buckets["medium_standard"].append(name)
                else:
                    buckets["medium_tricky"].append(name)
            else:  # TAIL
                if profile.rarity > 0.8:
                    buckets["tail_rare"].append(name)
                else:
                    buckets["tail_hard"].append(name)

        return buckets

    def summary(self) -> str:
        """生成映射器摘要"""
        dist = self.get_category_distribution()
        lines = [
            "=== Semantic Mapper Summary ===",
            f"Total tasks: {len(self.task_profiles)}",
            f"  HEAD:   {len(dist[TailCategory.HEAD])} tasks",
            f"  MEDIUM: {len(dist[TailCategory.MEDIUM])} tasks",
            f"  TAIL:   {len(dist[TailCategory.TAIL])} tasks",
            "",
            "Task Details:",
        ]

        for cat in [TailCategory.HEAD, TailCategory.MEDIUM, TailCategory.TAIL]:
            for p in dist[cat]:
                lines.append(
                    f"  [{cat.value:6s}] {p.name:30s} "
                    f"score={p.tail_score:.3f} "
                    f"rarity={p.rarity:.2f} diff={p.difficulty:.2f} "
                    f"fail={p.failure_rate:.2f}"
                )

        return "\n".join(lines)
