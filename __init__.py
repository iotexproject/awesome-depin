"""
Q-TAIL-MVP: Quantum-Guided Tail Distribution Engine for Embodied Learning

核心公式: q = (1-η)b + ηPs
- b: 基线分布 (uniform / empirical)
- Ps: 量子源先验 (Porter-Thomas 分布)
- η: 插值系数
"""

__version__ = "0.1.0"
