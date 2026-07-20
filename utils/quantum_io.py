import os
import json
import pandas as pd
from typing import Dict, Any

def save_counts_csv(counts: Dict[str, int], shots: int, filepath: str):
    """保存原始测量计数的 CSV 文件"""
    data = []
    for bitstring, count in counts.items():
        data.append({
            "bitstring": bitstring,
            "count": count,
            "probability": count / shots
        })
    df = pd.DataFrame(data)
    df.to_csv(filepath, index=False)

def save_probs_csv(probs_dict: Dict[str, float], n_qubits: int, filepath: str):
    """保存标准化的概率分布 CSV 文件"""
    N = 2 ** n_qubits
    data = []
    for bitstring, prob in probs_dict.items():
        data.append({
            "bitstring": bitstring,
            "probability": prob,
            "normalized_probability": N * prob
        })
    df = pd.DataFrame(data)
    df.to_csv(filepath, index=False)

def save_run_metadata(metadata: Dict[str, Any], filepath: str):
    """保存单次采集的元数据"""
    with open(filepath, 'w') as f:
        json.dump(metadata, f, indent=4)

def update_manifest(metadata: Dict[str, Any], manifest_path: str = "data/quantum_runs/manifest.json"):
    """更新全局任务清单"""
    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
    manifest = []
    if os.path.exists(manifest_path):
        with open(manifest_path, 'r') as f:
            try:
                manifest = json.load(f)
            except json.JSONDecodeError:
                pass
    manifest.append(metadata)
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=4)

def update_latest_run(metadata: Dict[str, Any], latest_path: str = "data/latest_quantum_run.json"):
    """记录最新一次成功的任务，供其他 agent 快速读取"""
    with open(latest_path, 'w') as f:
        json.dump(metadata, f, indent=4)

def generate_page_json(metadata: Dict[str, Any], run_dir: str, page_json_path: str = "results/page_quantum_source.json"):
    """生成专供前端页面消费的摘要数据"""
    os.makedirs(os.path.dirname(page_json_path), exist_ok=True)
    page_data = {
        "title": "量子源数据：真实物理系统的非均匀先验",
        "source_file": os.path.join(run_dir, "probs.csv"),
        "backend": metadata.get("backend"),
        "n_qubits": metadata.get("n_qubits"),
        "depth": metadata.get("depth"),
        "shots": metadata.get("shots"),
        "support_size": metadata.get("observed_support_size"),
        "entropy": metadata.get("entropy"),
        "cv": metadata.get("cv"),
        "gini": metadata.get("gini"),
        "chart_png": os.path.join(run_dir, "pt_plot.png"),
        "chart_svg": os.path.join(run_dir, "pt_plot.svg"),
        "short_description": "基于真实量子芯片的随机电路采样数据，呈现典型的重尾非均匀分布特性，为长尾任务调度提供结构化探索空间。"
    }
    with open(page_json_path, 'w') as f:
        json.dump(page_data, f, indent=4)
