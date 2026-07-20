# Q-TAIL Full Dataset Download Without VPN

服务器不能装 VPN 时，不要在训练服务器上硬连 Google Cloud Storage。优先用下面两条路线。

## 路线 A：Hugging Face / LeRobot 镜像

适合：服务器能访问 Hugging Face，且训练代码可以接受 LeRobot/Parquet/MP4 格式，或你愿意做格式 adapter。

### DROID 镜像

公开页面：

- https://huggingface.co/datasets/cadene/droid
- https://huggingface.co/datasets/lerobot/droid_1.0.1

下载：

```bash
export DATA_DISK=/path/to/4t_disk/qtail_full_data
mkdir -p "$DATA_DISK/hf"
python3 -m pip install -U huggingface_hub hf_transfer
export HF_HUB_ENABLE_HF_TRANSFER=1

huggingface-cli download cadene/droid \
  --repo-type dataset \
  --local-dir "$DATA_DISK/hf/cadene_droid" \
  --resume-download
```

如果 `cadene/droid` 不稳定，换 LeRobot 版本：

```bash
huggingface-cli download lerobot/droid_1.0.1 \
  --repo-type dataset \
  --local-dir "$DATA_DISK/hf/lerobot_droid_1_0_1" \
  --resume-download
```

注意：这不是官方 RLDS bucket 的逐字节镜像，而是 LeRobot/社区转换格式。能用于训练，但需要在训练管线里明确记录 claim boundary：`source_format=LeRobot mirror`。

### Open X / RT-X 镜像

公开页面：

- https://huggingface.co/datasets/jxu124/OpenX-Embodiment
- https://huggingface.co/collections/lerobot/open-x-embodiment

流式读取单个 Open X 子数据集：

```python
import datasets

ds = datasets.load_dataset(
    "jxu124/OpenX-Embodiment",
    "bridge",
    streaming=True,
    split="train",
)
for row in ds:
    print(row.keys())
    break
```

下载某个 LeRobot Open X 子集，例如：

```bash
huggingface-cli download lerobot/stanford_kuka_multimodal_dataset \
  --repo-type dataset \
  --local-dir "$DATA_DISK/hf/openx/stanford_kuka_multimodal_dataset" \
  --resume-download
```

## 路线 B：云主机中转，不在训练服务器装 VPN

适合：训练服务器访问不了 GCS，但能 SSH/rsync 到一台海外云主机。

### 1. 在 GCP/AWS/海外云主机下载官方 GCS 数据

```bash
export RELAY_DISK=/mnt/qtail_relay
mkdir -p "$RELAY_DISK"/{droid,openx}
python3 -m pip install -U gsutil

gsutil -m rsync -r gs://gresearch/robotics/droid "$RELAY_DISK/droid"
gsutil ls gs://gdm-robotics-open-x-embodiment/ | while read -r uri; do
  name=$(basename "$uri")
  gsutil -m rsync -r "$uri" "$RELAY_DISK/openx/$name" || true
done
```

### 2. 从训练服务器拉回数据

```bash
export DATA_DISK=/path/to/4t_disk/qtail_full_data
mkdir -p "$DATA_DISK"

rsync -avP --partial --append-verify relay_user@relay_host:/mnt/qtail_relay/droid "$DATA_DISK/"
rsync -avP --partial --append-verify relay_user@relay_host:/mnt/qtail_relay/openx "$DATA_DISK/"
```

如果服务器只能访问国内对象存储，就在中转机上传到 OSS/COS/S3 兼容桶，再让训练服务器从该桶下载。

## 路线 C：只训练 DROID full，Open X 先用镜像/流式

如果 4 TiB 盘空间紧张，最稳的第一版 full run 是：

1. DROID：用官方 RLDS 全量数据，或 Hugging Face LeRobot DROID 镜像。
2. Open X：先选 3-5 个子集跑 Q-Tail allocation，对齐训练接口。
3. 等 pipeline 稳定后再扩到更多 Open X 子集。

这样能先得到一个真实训练结果，不被 Open X 全量规模和网络问题卡死。

## 快速决策

- 能访问 Hugging Face：先用路线 A。
- 只能访问 SSH：用路线 B。
- 需要严格官方 RLDS 格式：用路线 B。
- 只要先拿真实训练结论：DROID full 优先，Open X 先子集化。
