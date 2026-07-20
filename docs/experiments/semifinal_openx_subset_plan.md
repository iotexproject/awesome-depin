# Q-TAIL Semifinal Open X Subset Plan

目标：硬盘只剩约 1.2 TiB 时，不下载 Open X 全量，不下载 829GB KUKA 大包；改用可控真实 Open X 子集，跑出半决赛能讲清楚、能复跑的证据。

## 结论

不要下载：

```text
gs://gdm-robotics-open-x-embodiment/kuka
```

原因：`kuka/0.1.0` 约 `772.45 GiB`，加上训练缓存、checkpoint、日志后风险太高。

推荐下载 Strong Evidence 包：约 `171.62 GiB`，即使按 3 倍训练/缓存/checkpoint 空间估算也约 `514.87 GiB`，适合 1.2 TiB 磁盘。

## 子集大小

| Dataset | Size |
|---|---:|
| `language_table` | `46.90 GiB` |
| `language_table_sim` | `93.08 GiB` |
| `berkeley_mvp_converted_externally_to_rlds` | `12.34 GiB` |
| `austin_sirius_dataset_converted_externally_to_rlds` | `6.55 GiB` |
| `nyu_door_opening_surprising_effectiveness` | `7.12 GiB` |
| `columbia_cairlab_pusht_real` | `2.80 GiB` |
| `austin_buds_dataset_converted_externally_to_rlds` | `1.49 GiB` |
| `ucsd_kitchen_dataset_converted_externally_to_rlds` | `1.33 GiB` |

## 下载到项目 data 目录

```bash
export OPENX_DIR=/Users/avalok/work/Q-TAIL-MVP/data/openx_semifinal
export GSUTIL=/Users/avalok/Library/Python/3.12/bin/gsutil
mkdir -p "$OPENX_DIR"

$GSUTIL -m rsync -r gs://gdm-robotics-open-x-embodiment/language_table "$OPENX_DIR/language_table"
$GSUTIL -m rsync -r gs://gdm-robotics-open-x-embodiment/language_table_sim "$OPENX_DIR/language_table_sim"
$GSUTIL -m rsync -r gs://gdm-robotics-open-x-embodiment/berkeley_mvp_converted_externally_to_rlds "$OPENX_DIR/berkeley_mvp_converted_externally_to_rlds"
$GSUTIL -m rsync -r gs://gdm-robotics-open-x-embodiment/austin_sirius_dataset_converted_externally_to_rlds "$OPENX_DIR/austin_sirius_dataset_converted_externally_to_rlds"
$GSUTIL -m rsync -r gs://gdm-robotics-open-x-embodiment/nyu_door_opening_surprising_effectiveness "$OPENX_DIR/nyu_door_opening_surprising_effectiveness"
$GSUTIL -m rsync -r gs://gdm-robotics-open-x-embodiment/columbia_cairlab_pusht_real "$OPENX_DIR/columbia_cairlab_pusht_real"
$GSUTIL -m rsync -r gs://gdm-robotics-open-x-embodiment/austin_buds_dataset_converted_externally_to_rlds "$OPENX_DIR/austin_buds_dataset_converted_externally_to_rlds"
$GSUTIL -m rsync -r gs://gdm-robotics-open-x-embodiment/ucsd_kitchen_dataset_converted_externally_to_rlds "$OPENX_DIR/ucsd_kitchen_dataset_converted_externally_to_rlds"
```

## 如果时间很紧

先下载 Demo 包，约 `31.63 GiB`：

```bash
export OPENX_DIR=/Users/avalok/work/Q-TAIL-MVP/data/openx_demo
export GSUTIL=/Users/avalok/Library/Python/3.12/bin/gsutil
mkdir -p "$OPENX_DIR"

$GSUTIL -m rsync -r gs://gdm-robotics-open-x-embodiment/berkeley_mvp_converted_externally_to_rlds "$OPENX_DIR/berkeley_mvp_converted_externally_to_rlds"
$GSUTIL -m rsync -r gs://gdm-robotics-open-x-embodiment/austin_sirius_dataset_converted_externally_to_rlds "$OPENX_DIR/austin_sirius_dataset_converted_externally_to_rlds"
$GSUTIL -m rsync -r gs://gdm-robotics-open-x-embodiment/nyu_door_opening_surprising_effectiveness "$OPENX_DIR/nyu_door_opening_surprising_effectiveness"
$GSUTIL -m rsync -r gs://gdm-robotics-open-x-embodiment/columbia_cairlab_pusht_real "$OPENX_DIR/columbia_cairlab_pusht_real"
$GSUTIL -m rsync -r gs://gdm-robotics-open-x-embodiment/austin_buds_dataset_converted_externally_to_rlds "$OPENX_DIR/austin_buds_dataset_converted_externally_to_rlds"
$GSUTIL -m rsync -r gs://gdm-robotics-open-x-embodiment/ucsd_kitchen_dataset_converted_externally_to_rlds "$OPENX_DIR/ucsd_kitchen_dataset_converted_externally_to_rlds"
```

## 半决赛表达口径

可以这样说：

```text
我们没有把 3.05 TiB Open X 全量数据塞进仓库，也没有把硬盘风险转嫁给评测环境。
半决赛采用 Open X 官方 GCS 的真实 RLDS 子集，覆盖语言桌面任务、仿真任务、真实操作任务和门/厨房/推物等多任务场景。
在同一数据子集上，我们固定模型、训练步数、算力预算和评测协议，对比原始采样与 Q-Tail 长尾采样。
全量 Open X 扩展路径已经给出，当前结果属于真实子集 full-run，不是聚合元数据模拟。
```

## 训练与服务实现

Strong 下载完整性门禁通过后，后台任务自动执行：

```bash
python3 tools/qtail_train_openx_demo.py \
  --data-dir data/openx_demo \
  --out results/openx_strong_training \
  --steps 20000 \
  --records-per-shard 4 \
  --min-record-parse-rate 0.95 \
  --wait 0
```

训练器只读取完成并改名的 TFRecord，排除 `.gstmp/.tmp/.part`。它覆盖全部完整 shard，并从每个 shard 解码真实 episode，提取 episode length、reward、action statistics、instruction complexity 和 terminal rate，训练 PyTorch allocation head，保存 `qtail_allocation_head.pt`、SHA256、训练行和报告。

服务层把训练得到的 Open X tail quantile gain curve 映射到客户任务的 tail-score 分位数，重新归一化到同一 synthetic budget，输出 `qtail_service_synthetic_plan.csv` 和客户交付 zip。

Claim boundary：这是 record-informed PT 重尾数据分配/生成规划模型；它证明模型能把同预算生成资源转向罕见/高风险任务。它不是端到端机器人 policy，也不能替代使用同一 policy、同一环境、同一步数的下游策略训练验证。

## 决策

- 想快点出结果：先下 Demo 包。
- 想半决赛更有分量：下 Strong Evidence 包。
- 不要下 KUKA，除非你有额外至少 2 TiB 空闲空间。
