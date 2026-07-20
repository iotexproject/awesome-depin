from __future__ import annotations

from pathlib import Path

import nbformat as nbf


OUT = Path(__file__).resolve().parent
NOTEBOOK = OUT / "qtail_buyer_assessment.ipynb"


def md(text: str):
    return nbf.v4.new_markdown_cell(text.strip())


def code(text: str):
    return nbf.v4.new_code_cell(text.strip())


nb = nbf.v4.new_notebook()
nb["metadata"] = {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python", "version": "3"},
}

nb["cells"] = [
    md(
        """
# Q-Tail 具身机器人厂商买方评估

## tl;dr

- 当前交付物应被定义为**长尾任务分析、预算分配与场景规格服务**，而不是可直接训练策略的合成轨迹数据集。
- 项目内部的同预算响应模型显示长尾成功率提升 **5.41 个百分点**、CVaR@20 提升 **5.56 个百分点**，但这仍是模型化评估，不是同策略训练或真实机器人闭环增益。
- 本评估的加权结果为：**数据本体采购准备度 34.5/100**；**长尾分配服务准备度 58.0/100**。前者不足以进入正式数据采购，后者具备设计伙伴或小额 PoC 价值。
"""
    ),
    md(
        """
## Context & Methods

### 决策问题

从具身智能机器人厂商的数据、算法、采购和合规团队视角，判断 Q-Tail 当前是否已达到“购买训练数据”或“购买数据服务”的门槛，以及需要补齐哪些证据。

### Key Assumptions

- 评分是买方尽调框架下的专家判断，不是公开统一行业标准。
- `80+` 视为可进入生产采购，`65–79` 视为有条件付费 PoC，`50–64` 视为设计伙伴验证，`<50` 视为当前不采购该商品形态。
- 项目仓库中的最新公开服务包与 Strong 训练报告，被视为当前可供买方审阅的最强证据。
- “合成数据本体”必须包含可供政策训练消费的逐步观测、动作、状态、时间戳与任务元数据；仅有分配权重和场景说明不计为训练轨迹。
"""
    ),
    md("## Data\n\n### 1. 加载当前公开服务包与 Strong 训练证据"),
    code(
        """
from pathlib import Path
import json
import subprocess
import zipfile

import pandas as pd


def find_root() -> Path:
    cwd = Path.cwd().resolve()
    candidates = [cwd, *cwd.parents]
    for candidate in candidates:
        if (candidate / "README.md").exists() and (candidate / "results/qtail_openx_service_public").exists():
            return candidate
    raise FileNotFoundError("Could not locate Q-TAIL-MVP root")


ROOT = find_root()
OUT = ROOT / "output/qtail_buyer_assessment_20260715"
PACKAGE = ROOT / "results/qtail_openx_service_public"

synthetic = pd.read_csv(PACKAGE / "qtail_synthetic_data.csv")
service_plan = pd.read_csv(PACKAGE / "qtail_service_synthetic_plan.csv")
task_profiles = pd.read_csv(PACKAGE / "task_profiles.csv")
strong_rows = pd.read_csv(ROOT / "results/openx_strong_training/openx_shard_training_rows.csv")
service_report = json.loads((PACKAGE / "qtail_service_delivery_report.json").read_text(encoding="utf-8"))
engine_report = json.loads((PACKAGE / "qtail_data_engine_report.json").read_text(encoding="utf-8"))
model_card = json.loads((PACKAGE / "qtail_service_model_card.json").read_text(encoding="utf-8"))
strong_report = json.loads((ROOT / "results/openx_strong_training/openx_demo_training_report.json").read_text(encoding="utf-8"))

print(f"Workspace: {ROOT}")
print(f"Current package rows: {len(synthetic)}")
"""
    ),
    md("### 2. 盘点当前可证实的产品与训练事实"),
    code(
        """
zip_path = PACKAGE / "qtail_delivery_package.zip"
with zipfile.ZipFile(zip_path) as archive:
    zip_members = archive.infolist()

effect = service_report["effect_summary"]
training = model_card["training_source"]
facts = pd.DataFrame([
    ["公开服务任务画像", len(synthetic), "task profiles"],
    ["服务包 ZIP 大小", round(zip_path.stat().st_size / 1024, 1), "KiB"],
    ["服务包内文件", len(zip_members), "files"],
    ["服务包解压后体积", sum(m.file_size for m in zip_members), "bytes"],
    ["Strong 本地源数据", training["total_gib"], "GiB"],
    ["Strong 数据集数", len(training["datasets"]), "datasets"],
    ["Strong 完整分片", training["shard_count"], "shards"],
    ["Strong 解码 episode", training["trajectory_evidence"]["records_decoded"], "episodes"],
    ["每分片解码上限", training["trajectory_evidence"]["records_per_shard_cap"], "episodes/shard"],
    ["分配头参数", training["model_artifact"]["parameter_count"], "parameters"],
    ["优化步数", training["steps"], "steps"],
    ["响应模型长尾成功率增益", effect["tail_success_gain_pp"], "percentage points"],
    ["响应模型 CVaR@20 增益", effect["cvar20_gain_pp"], "percentage points"],
    ["长尾数据份额增益", effect["tail_data_share_gain_pp"], "percentage points"],
], columns=["fact", "value", "unit"])
facts
"""
    ),
    md("## Results\n\n### 3. 数据质量与直接可训练性检查"),
    code(
        """
trajectory_keywords = (
    "image", "camera", "action", "joint", "pose", "timestamp", "video",
    "depth", "force", "tactile", "proprio", "observation"
)
trajectory_fields = [
    column for column in synthetic.columns
    if any(keyword in column.lower() for keyword in trajectory_keywords)
]

quality_checks = pd.DataFrame([
    ["任务 ID 唯一", synthetic["task_id"].nunique() == len(synthetic), f"{synthetic['task_id'].nunique()}/{len(synthetic)}", "通过"],
    ["分配份额和为 1", abs(synthetic["synthetic_share"].sum() - 1.0) < 1e-9, f"{synthetic['synthetic_share'].sum():.9f}", "通过"],
    ["合成预算和为 100k", abs(synthetic["synthetic_count"].sum() - 100_000) < 1e-6, f"{synthetic['synthetic_count'].sum():.1f}", "通过"],
    ["核心字段无空值", int(synthetic.isna().sum().sum()) == 0, f"nulls={int(synthetic.isna().sum().sum())}", "通过"],
    ["包含逐步观测/动作字段", bool(trajectory_fields), str(trajectory_fields), "未通过"],
    ["包含相机标定/机器人构型", False, "服务包未提供", "未通过"],
    ["包含 RLDS/LeRobot 可加载产物", False, "仅 CSV/JSON/ZIP", "未通过"],
    ["存在独立 holdout/validation", any(strong_report.get(k) for k in ["validation", "split", "holdout"]), "Strong 报告未记录", "未通过"],
], columns=["check", "passed", "evidence", "status"])
quality_checks
"""
    ),
    md("### 4. 证据可信度与文档一致性检查"),
    code(
        """
delivery_readme = (PACKAGE / "README_QTAIL_DELIVERY.md").read_text(encoding="utf-8")
tracked_tests = subprocess.run(
    ["git", "ls-files", "tests/**", "test_*.py", "*_test.py"],
    cwd=ROOT,
    check=True,
    capture_output=True,
    text=True,
).stdout.splitlines()

evidence_checks = pd.DataFrame([
    ["Strong 训练状态", strong_report.get("status"), "完整" if strong_report.get("status") == "complete" else "需修复"],
    ["全分片解析", f"{int(strong_rows['record_parse_ok'].sum())}/{len(strong_rows)}", "完整"],
    ["独立验证集", strong_report.get("validation"), "缺失"],
    ["策略训练/闭环 rollout", service_report["service_steps"][-1]["status"], "缺失"],
    ["仓库内受版本控制自动化测试", len(tracked_tests), "缺失" if not tracked_tests else "存在"],
    ["服务包文档是否仍称 Strong 待完成", "final Strong run is gated" in delivery_readme, "冲突"],
    ["复现命令是否仍引用 incremental", "openx_incremental_training_snapshot" in delivery_readme, "冲突"],
], columns=["item", "observed", "assessment"])
evidence_checks
"""
    ),
    md("### 5. 买方加权评分：数据本体与分配服务分开评估"),
    code(
        """
data_scorecard = pd.DataFrame([
    ["直接可训练性与标准格式", 20, 1.0, "仅 114 行任务分配；无观测—动作轨迹"],
    ["下游策略增益与真实机器人证据", 20, 1.0, "只有响应模型；无同策略训练和闭环实测"],
    ["机型/任务适配与物理有效性", 15, 1.5, "无具体机器人构型、物理仿真或 sim-to-real 证据"],
    ["长尾覆盖与分配差异化", 10, 3.5, "长尾调度清晰，内部同预算门槛通过"],
    ["质量、审计与可复现性", 10, 3.0, "模型卡、清单、校验器较完整；证据层级仍低"],
    ["集成与工程成熟度", 10, 2.5, "有 API/ZIP；无 RLDS/LeRobot/训练适配器"],
    ["授权、合规与安全", 5, 1.5, "缺少数据权利矩阵、隐私/安全与客户部署说明"],
    ["规模、成本与 SLA", 5, 1.5, "无可售轨迹吞吐、单价、时延和 SLA"],
    ["独立泛化与 holdout", 5, 1.0, "无独立测试集、客户盲测或跨机器人泛化"],
], columns=["criterion", "weight", "score_0_to_5", "evidence"])
data_scorecard["weighted_points"] = data_scorecard["weight"] * data_scorecard["score_0_to_5"] / 5

service_scorecard = pd.DataFrame([
    ["长尾问题适配", 20, 4.0, "买方确有尾部覆盖与失败场景发现需求"],
    ["分配方法证据", 20, 2.5, "真实 RLDS 特征参与，但目标与验证仍主要由内部模型构造"],
    ["客户输入与结果可执行性", 15, 3.0, "CSV/API 简单；场景规格仍需下游 renderer/采集系统"],
    ["工程集成与运营", 15, 2.5, "本地 API/包交付可用；缺生产认证、监控和权限体系"],
    ["审计与复现", 10, 3.5, "同预算审计、模型卡、哈希和校验器是明显优点"],
    ["商业 ROI 证据", 10, 2.0, "尚未证明降低每个有效策略增益点的成本"],
    ["安全合规", 5, 1.5, "缺本地/VPC 交付、DPA、权限和数据保留政策"],
    ["差异化", 5, 3.0, "PT 长尾分配有叙事和 IP，但量子优势尚未被证明"],
], columns=["criterion", "weight", "score_0_to_5", "evidence"])
service_scorecard["weighted_points"] = service_scorecard["weight"] * service_scorecard["score_0_to_5"] / 5

def readiness(points: float) -> str:
    if points >= 80:
        return "生产采购准备"
    if points >= 65:
        return "有条件付费 PoC"
    if points >= 50:
        return "设计伙伴验证"
    return "当前不采购该商品形态"

scores = pd.DataFrame([
    ["合成数据本体", data_scorecard["weighted_points"].sum()],
    ["长尾分配/评测服务", service_scorecard["weighted_points"].sum()],
], columns=["offer", "score_0_to_100"])
scores["readiness"] = scores["score_0_to_100"].map(readiness)

display(scores)
display(data_scorecard)
display(service_scorecard)
"""
    ),
    md("### 6. 达标矩阵与采购判断"),
    code(
        """
gate_matrix = pd.DataFrame([
    ["长尾任务识别/预算重分配", "必须", "达到初步门槛", "同预算分配守恒、内部尾部指标改善"],
    ["可直接加载的轨迹格式", "必须", "未达到", "无 RGB/状态/动作/时间戳/RLDS/LeRobot"],
    ["同策略同预算训练 uplift", "必须", "未达到", "当前是响应模型，不是政策训练"],
    ["真实机器人或高保真闭环验证", "必须", "未达到", "full policy handoff 仍 pending"],
    ["简单基线和非量子对照", "必须", "部分达到", "模拟矩阵存在，但当前服务证据不足"],
    ["数据质量与审计", "必须", "部分达到", "分配表完整；轨迹级质量指标不存在"],
    ["数据权利/隐私/安全", "必须", "未达到", "缺采购法务所需材料"],
    ["成本、吞吐、交付 SLA", "商业必需", "未达到", "尚无可采购单位经济性"],
], columns=["buyer_gate", "importance", "current_status", "evidence"])
gate_matrix
"""
    ),
    md(
        """
## Takeaways

1. **当前不会以“训练数据集”名义被主流机器人厂商正式采购。** 交付包是任务分配和场景规格，缺少买方训练栈真正消费的逐步多模态数据。
2. **可以争取设计伙伴或小额 PoC。** 最有说服力的切入点是“客户上传任务/失败统计 → 输出长尾缺口、预算方案和审计”，而不是出售 CSV 为合成数据。
3. **内部 +5.41 pp 尾部成功率不能当作采购承诺。** 响应函数与尾部定义由本项目设定，且分配器正是针对这些尾部指标优化；需要同一 VLA/策略、同预算、独立任务和闭环 rollout 验证。
4. **量子标签目前不是采购加分项。** 买方首先比较真实增益、成本和集成；在没有 PT 对经典重尾/优先级采样的独立优势证据前，量子叙事会增加技术尽调成本。
5. **下一里程碑应是一个窄而完整的闭环。** 选定单一机器人构型与 3–5 个高价值尾部任务，产出 RLDS/LeRobot 轨迹，并完成基线与 Q-Tail 数据下的同策略训练、仿真闭环和小规模真机复核。
"""
    ),
    md("### 保存可复核评分与摘要"),
    code(
        """
OUT.mkdir(parents=True, exist_ok=True)
data_scorecard.to_csv(OUT / "data_procurement_scorecard.csv", index=False)
service_scorecard.to_csv(OUT / "service_procurement_scorecard.csv", index=False)
gate_matrix.to_csv(OUT / "buyer_gate_matrix.csv", index=False)

summary = {
    "as_of": "2026-07-15",
    "data_procurement_score": float(data_scorecard["weighted_points"].sum()),
    "service_procurement_score": float(service_scorecard["weighted_points"].sum()),
    "package_rows": int(len(synthetic)),
    "package_columns": list(synthetic.columns),
    "trajectory_fields": trajectory_fields,
    "zip_size_bytes": zip_path.stat().st_size,
    "zip_uncompressed_bytes": sum(m.file_size for m in zip_members),
    "strong_datasets": len(training["datasets"]),
    "strong_shards": int(training["shard_count"]),
    "strong_decoded_episodes": int(training["trajectory_evidence"]["records_decoded"]),
    "tail_success_gain_pp_response_model": float(effect["tail_success_gain_pp"]),
    "cvar20_gain_pp_response_model": float(effect["cvar20_gain_pp"]),
    "quality_checks": quality_checks.to_dict(orient="records"),
    "evidence_checks": evidence_checks.astype(object).where(pd.notna(evidence_checks), None).to_dict(orient="records"),
}
(OUT / "analysis_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

print("Saved:")
for name in ["data_procurement_scorecard.csv", "service_procurement_scorecard.csv", "buyer_gate_matrix.csv", "analysis_summary.json"]:
    print(f"- {OUT / name}")
"""
    ),
]

nbf.write(nb, NOTEBOOK)
print(NOTEBOOK)
