# Q-TAIL Full Dataset Download

目标：先把真实 full trajectory 数据下载到 4 TiB 数据盘，后续再跑同算力、同训练步数、同环境的 Q-Tail full-training 对比。

## 0. 准备

把下面的路径改成你的 4 TiB 数据盘挂载点：

```bash
export DATA_DISK=/Volumes/YOUR_4T_DISK/qtail_full_data
mkdir -p "$DATA_DISK"/{droid,openx/tensorflow_datasets}
python3 -m pip install -U gsutil
```

## 1. DROID 全量数据

官方主页：

- https://droid-dataset.github.io/
- https://github.com/droid-dataset/droid_policy_learning

下载 RLDS 训练数据：

```bash
gsutil -m cp -r gs://gresearch/robotics/droid "$DATA_DISK/droid/"
```

断点/增量续跑推荐：

```bash
gsutil -m rsync -r gs://gresearch/robotics/droid "$DATA_DISK/droid/droid"
```

可选：先下载 100 条轨迹小样本测试环境：

```bash
gsutil -m cp -r gs://gresearch/robotics/droid_100 "$DATA_DISK/droid/"
```

可选：原始 stereo/full-HD 数据，不是常规 RLDS 训练必需：

```bash
gsutil -m cp -r gs://gresearch/robotics/droid_raw "$DATA_DISK/droid_raw/"
```

## 2. Open X / RT-X 数据

官方主页：

- https://robotics-transformer-x.github.io/
- https://github.com/google-deepmind/open_x_embodiment

查看公开 bucket 里的 dataset 名称：

```bash
gsutil ls gs://gdm-robotics-open-x-embodiment/
```

下载单个 dataset：

```bash
gsutil -m cp -r gs://gdm-robotics-open-x-embodiment/<dataset_name> "$DATA_DISK/openx/tensorflow_datasets/"
```

按官方 TFDS 目录结构下载全部可公开访问的 dataset：

```bash
gsutil ls gs://gdm-robotics-open-x-embodiment/ | while read -r uri; do
  gsutil -m cp -r "$uri" "$DATA_DISK/openx/tensorflow_datasets/" || true
done
```

断点/增量续跑版本：

```bash
gsutil ls gs://gdm-robotics-open-x-embodiment/ | while read -r uri; do
  name=$(basename "$uri")
  gsutil -m rsync -r "$uri" "$DATA_DISK/openx/tensorflow_datasets/$name" || true
done
```

## 3. 下载后快速检查

```bash
du -sh "$DATA_DISK"/droid "$DATA_DISK"/openx
find "$DATA_DISK" -maxdepth 3 -type d | head -80
```

训练时把 DROID 的 `DATA_PATH` 指到同一个数据根目录，例如：

```bash
export DATA_PATH="$DATA_DISK"
```

## Notes

- DROID 官方 README 给的 full RLDS 下载命令是 `gsutil -m cp -r gs://gresearch/robotics/droid <target>`.
- Open X 官方 README 给的手动下载模板是 `gsutil -m cp -r gs://gdm-robotics-open-x-embodiment/{dataset_name} ~/tensorflow_datasets/`.
- 如果 Open X 某些 bucket 目录为空或不可下载，先保留日志；官方 bucket 中可能存在 folder marker 或非公开完整对象。
