# Q-Tail Open X Training Status Brief

- Generated: 2026-07-10T17:58:19.173882+08:00 (Asia/Shanghai)
- Page: http://localhost:6222/qtail-openx-training
- Status: ready_as_incremental_evidence

## Current Download

- Active dataset: None
- Progress: 1/1 files, 100%
- Disk GiB: 171.62
- Trainable GiB: 171.62
- Strong ready: True
- Download health: no_active_gsutil_process · gsutil processes: 0 · retries in tail window: 1256
- Download acceleration: threads=16 · sliced_threshold=256M · components=8
- Download watchdog: restart_requested · byte growth since last check: 0 · no-growth seconds: 0
- Partial download files: 0 files · 0.000 GiB · recent active 0

## Latest Incremental Training

- Trainable input: 166.12 GiB
- Rows: 552
- Partial rows: 0
- Predicted tail share gain: 41.91 pp
- Next incremental refresh at: 168.12 GiB or 553 complete shards
- Remaining to next refresh: 0.000 GiB or 1 complete shards

## Service Package Metrics

- Public tail success gain: 5.41 pp
- Public tail success relative gain: 11.31%
- Public tail data share gain: 34.43 pp
- Latest API tail success gain: 35.06 pp

## Productized Service Execution

- Stage: incremental_openx_trained_service_live
- Thesis: Train and operate a Q-Tail model that converts customer embodied-AI data profiles into PT-heavy-tail synthetic data allocation packages, so customers can spend the same training budget on more rare/high-risk tasks.
- Next milestone: run 20000-step Strong training, rebuild service package, run post-Strong customer API sample, refresh page

## Strong Dataset Completion

### language_table

- Valid: True
- GiB: 46.90 / 46.00 (102.0%)
- TFRecord: 61 / 60 (101.7%)
- Remaining: 0.00 GiB, 0 TFRecords
- Partial files: 0

### language_table_sim

- Valid: True
- GiB: 93.08 / 80.00 (116.3%)
- TFRecord: 173 / 20 (865.0%)
- Remaining: 0.00 GiB, 0 TFRecords
- Partial files: 0

## Can Claim Now

- Real Open X files are being downloaded into data/openx_demo and monitored.
- Current incremental allocation-head training uses complete files only, excluding .gstmp/.tmp/.part partial downloads.
- The current Q-Tail allocation head is directionally aligned with the PT-heavy-tail goal.
- The local API can turn new embodied-task CSV data into a Q-Tail synthetic allocation package.
- The public customer-style service package passes the same-budget data-engine audit.

## Cannot Claim Yet

- Final Strong 20000-step training is not complete.
- Full robot-policy training has not been completed on the full RLDS/TFDS stack.
- Cannot yet claim language_table and language_table_sim are fully downloaded and verified.

## Next Trigger

- Strong training: ready_for_strong_training=true
- Incremental refresh: complete-file growth reaches min_growth_gib

## Gate Decisions

### Incremental retrain

- Status: ready
- Release condition: complete-file trainable data grows by at least min_growth_gib or min_new_shards
- Current evidence: trainable_gib=171.622; next_refresh_at_gib=168.125; growth_since_refresh_gib=5.497; current_shards=552; next_refresh_at_shards=553; shard_growth=0
- Next action: Run qtail_auto_refresh training

### Strong download verification

- Status: ready
- Release condition: language_table and language_table_sim meet size/metadata requirements and no partial files remain
- Current evidence: language_table_sim_gib=93.08; language_table_sim_partial_files=0; errors=
- Next action: Allow 20000-step Strong training

### Partial-byte exclusion

- Status: enforced
- Release condition: partial files are promoted to complete files by gsutil
- Current evidence: partial_files=0; partial_gib=0.0; recent_active=0
- Next action: Keep excluding .gstmp/.tmp/.part from training rows.

### Strong final training

- Status: complete
- Release condition: ready_for_strong_training=true
- Current evidence: download_complete=True; training_complete=True
- Next action: Run 20000-step training and rebuild service package after verification passes.

### Customer service package

- Status: live_incremental
- Release condition: latest validated training source is available
- Current evidence: auto_refresh_status=refreshed; last_refreshed_gib=166.125
- Next action: Serve current incremental model now; switch to Strong checkpoint after final training.

