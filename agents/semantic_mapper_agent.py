import os
import json
import numpy as np
from typing import Dict, List, Any

class SemanticMapperAgent:
    """
    Semantic Mapper Agent: Partitions MT10 tasks into Head/Medium/Tail,
    calculates tail scores, and provides base prior distributions (b).
    """
    def __init__(self):
        # 1. 读取 Meta-World MT10 的任务列表 (固定为 10 个)
        self.mt10_tasks = [
            "reach-v2", 
            "push-v2", 
            "pick-place-v2", 
            "door-open-v2", 
            "drawer-close-v2", 
            "button-press-topdown-v2", 
            "peg-insert-side-v2", 
            "window-open-v2", 
            "sweep-v2", 
            "basketball-v2"
        ]
        
        # 2. 定义固定的 head(4) / medium(3) / tail(3) 划分方案
        # 人工定义的 Zipf-like 频次向量 (模拟历史样本量/成功次数，降序排列)
        # 假设 head 任务样本量大，tail 任务样本量极少
        self.empirical_frequencies = np.array([
            10000, 8000, 6000, 4000,  # Head (reach, push, pick-place, door-open)
            1000, 800, 500,           # Medium (drawer-close, button-press, peg-insert)
            100, 50, 10               # Tail (window-open, sweep, basketball)
        ], dtype=float)

        self.taxonomy = {}
        self._build_taxonomy()

    def _build_taxonomy(self):
        """内部构建分类字典"""
        for i, task in enumerate(self.mt10_tasks):
            if i < 4:
                category = "head"
            elif i < 7:
                category = "medium"
            else:
                category = "tail"
                
            freq = self.empirical_frequencies[i]
            # 3. 为每个任务生成 tail score (1 / f_k，并做适当缩放以免数值过大)
            # 这里简单用 (max(freq) / freq) 来作为 tail score 的一种直观表达
            raw_score = self.empirical_frequencies[0] / freq
            
            self.taxonomy[task] = {
                "id": i,
                "category": category,
                "frequency": freq,
                "tail_score": raw_score
            }

    def build_mt10_tail_taxonomy(self) -> Dict[str, Any]:
        """返回完整的 MT10 长尾任务划分与统计信息"""
        summary = {
            "tasks": self.taxonomy,
            "groups": {
                "head": [t for t, v in self.taxonomy.items() if v["category"] == "head"],
                "medium": [t for t, v in self.taxonomy.items() if v["category"] == "medium"],
                "tail": [t for t, v in self.taxonomy.items() if v["category"] == "tail"],
            }
        }
        return summary

    def get_tail_scores(self) -> np.ndarray:
        """返回 10 维的 tail score 向量"""
        scores = np.array([self.taxonomy[task]["tail_score"] for task in self.mt10_tasks])
        # 归一化到一个合理区间，比如和为 1，或者 max 为 1。这里归一化为概率形式展示其相对权重。
        return scores / scores.sum()

    def generate_page_data(self, output_dir: str = "results"):
        """输出页面可展示的数据结构"""
        os.makedirs(output_dir, exist_ok=True)
        
        # 提取规范化的 tail scores
        scores = self.get_tail_scores()
        
        tasks_list = []
        for i, task in enumerate(self.mt10_tasks):
            tasks_list.append({
                "task_name": task,
                "tier": self.taxonomy[task]["category"],
                "tail_score": float(scores[i]),
                "base_frequency": float(self.taxonomy[task]["frequency"]),
                "display_order": i
            })
            
        page_data = {
            "title": "MT10 任务长尾映射",
            "description": "基于历史样本频率与难度，将 Meta-World MT10 划分为 Head, Medium, Tail 三个层级，并计算出每个任务的长尾分数（Tail Score），分数越高代表任务越罕见、越困难。",
            "tasks": tasks_list
        }
        
        out_path = os.path.join(output_dir, "page_mt10_taxonomy.json")
        with open(out_path, "w") as f:
            json.dump(page_data, f, indent=4)
        print(f"[SemanticMapperAgent] Page taxonomy data saved to {out_path}")
        return page_data

    def get_base_prior(self, mode: str = "uniform") -> np.ndarray:
        """
        4. 生成基础采样分布 b
        支持模式：
        - uniform: 均匀分布 [0.1, 0.1, ...]
        - empirical: 经验分布 (与 frequency 正相关)
        - invfreq: 逆频率分布 (与 1/frequency 正相关，即倾向于多采 tail)
        """
        n = len(self.mt10_tasks)
        if mode == "uniform":
            p = np.ones(n) / n
        elif mode == "empirical":
            p = self.empirical_frequencies.copy()
            p = p / p.sum()
        elif mode == "invfreq":
            p = 1.0 / self.empirical_frequencies
            p = p / p.sum()
        else:
            raise ValueError(f"Unknown mode: {mode}. Use 'uniform', 'empirical', or 'invfreq'.")
        return p

# 便捷模块级接口
_agent_instance = SemanticMapperAgent()

def build_mt10_tail_taxonomy() -> Dict[str, Any]:
    return _agent_instance.build_mt10_tail_taxonomy()

def get_tail_scores() -> np.ndarray:
    return _agent_instance.get_tail_scores()

def get_base_prior(mode: str = "uniform") -> np.ndarray:
    return _agent_instance.get_base_prior(mode)

def generate_page_data() -> Dict[str, Any]:
    return _agent_instance.generate_page_data()

if __name__ == "__main__":
    # Test execution
    taxonomy = build_mt10_tail_taxonomy()
    
    # Generate page data
    generate_page_data()
    print("Head tasks:", taxonomy["groups"]["head"])
    print("Medium tasks:", taxonomy["groups"]["medium"])
    print("Tail tasks:", taxonomy["groups"]["tail"])
    
    print("\nTail scores (normalized):")
    scores = get_tail_scores()
    for task, score in zip(_agent_instance.mt10_tasks, scores):
        print(f"  {task:25s}: {score:.4f}")
        
    print("\nBase priors:")
    for mode in ["uniform", "empirical", "invfreq"]:
        prior = get_base_prior(mode)
        print(f"  {mode:10s}: {np.round(prior, 4)}")
