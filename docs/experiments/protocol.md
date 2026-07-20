# Q-TAIL 验证协议 (Validation Protocol)

## 三阶段验证体系

Q-TAIL 的核心命题：**量子分布引导的长尾数据调度能够有效解决具身智能中的“灾难性遗忘”和“极端风险”（CVaR）。**

为了严谨地证明这一点，我们制定了三阶段的实验验证协议。当前项目处于**阶段 1**。

### 阶段 1：模拟基线验证 (Simulation Baseline)
- **目标**：验证在相同分布假设下，长尾采样的数学有效性。
- **环境**：纯统计学模拟器 (`experiments/mt10_sim.py`)。
- **方法**：通过 Beta 分布模拟 MT10 任务的训练动态。
- **指标**：Mean SR, Tail SR, CVaR@20，使用配对 t 检验和 Bootstrap 置信区间确保统计显著性。
- **状态**：**已完成**。模拟结果表明 pt-rank 显著提升了长尾任务的成功率。

### 阶段 2：真实 Meta-World 训练 (Real Meta-World Training)
- **目标**：在真实的 RL 环境中验证采样调度的有效性。
- **环境**：Meta-World MT10 基准测试，集成 Soft Actor-Critic (SAC) 或 Proximal Policy Optimization (PPO) 算法。
- **方法**：
  1. 收集 Quafu 真实量子硬件的 PT 先验分布数据。
  2. 映射为 MT10 任务的采样概率。
  3. 实际训练网络并评估真实奖励与成功率。
- **状态**：**筹备中**。此阶段需要 GPU 算力和完整的 RL 训练流水线。

### 阶段 3：真实机器人/高保真验证 (Real Robot / High-Fidelity Validation)
- **目标**：验证量子先验调度对解决“现实世界长尾”（Sim-to-Real Gap、罕见物理交互）的价值。
- **环境**：真实机械臂（如 Franka Emika Panda 或 UR5）及多样化的操作任务。
- **方法**：将 Meta-World 中证明有效的策略迁移到真实机器人上，测试在罕见任务中的泛化与鲁棒性。
- **状态**：**远期规划**。

## 声明与约束
- 不声称“量子优势已证明” (No Quantum Advantage Claims)。
- 不混淆阶段 1、2、3 的结果，当前所有结果必须明确标注为 `simulated`（模拟信号）。
- 绝不声称当前方法达到了现有技术状态 (SOTA)，重点在于方法论和机制探索。
