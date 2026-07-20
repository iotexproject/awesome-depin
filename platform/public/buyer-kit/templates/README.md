# Q-Tail 机器人厂商设计伙伴采购试点包

版本：1.2.0  
适用范围：从已完成的 Q-Tail Pro 生成任务推进到买方 Gate 1–3 验收与采购合同协商。

## 使用顺序

1. 双方先填写并确认 `pilot-sow-template.md`，冻结机器人、传感器、控制频率、任务、预算、数据格式、生产后端和验收责任人。
2. 买方生产后端执行 Gate 1。填写 `gate1-dataset-manifest.json` 和 `gate1-evidence.json`，对数据包、生产日志、原始证据包和买方签署件分别计算 SHA-256。
3. 买方或独立评测方执行 Gate 2。逐回合填写 `gate2-evaluation-ledger.csv`，从冻结原始记录计算指标，再填写 `gate2-evidence.json`。
4. 买方在真实机器人上执行 Gate 3。逐次填写 `gate3-real-robot-trials.csv`，用真实发票或经财务确认的成本账本填写 `gate3-commercial-cost-ledger.csv`，再填写 `gate3-evidence.json`。
5. 每道 Gate 使用 `buyer-signoff-template.md` 形成外部签署件。不要在 Q-Tail 内部生成或替代买方签名。
6. 运营人员核对原件、签署件、URL、哈希和阈值后才可批准。完成合规审查后才可生成 SOW 协商草案。
7. 双方真正签署外部采购合同后，按 `contract-execution-checklist.md` 归档执行件 SHA-256、双方签署人、双方各自的独立签署凭证 SHA-256、合同编号与生效日。

## SHA-256

macOS：

```bash
shasum -a 256 <文件>
```

Linux：

```bash
sha256sum <文件>
```

Windows PowerShell：

```powershell
Get-FileHash -Algorithm SHA256 <文件>
```

`evidence_artifact_sha256` 必须是该 Gate 冻结原始证据包的哈希；`buyer_signoff_sha256` 必须是买方或独立验收方已经签署的验收件哈希。两个字段不能使用 Q-Tail 本地仿真包、模板文件或示例文件的哈希替代。

## Gate 1 生产后端校验

买方在自己选择的生产后端完成轨迹导出后，将模板状态改为
`buyer_external_completed`，并运行随包提供的纯 Python 校验器：

```bash
python3 tools/validate_gate1_delivery.py \
  --manifest templates/gate1-dataset-manifest.json \
  --dataset-package /path/to/frozen-dataset-package.tar.gz \
  --production-log /path/to/backend-production.log \
  --report gate1-validation-report.json
```

校验器会核对机器人/传感器/频率/任务/格式、轨迹和帧数、数据包与日志
SHA-256、Q-Tail 来源任务以及 schema/playback 结果。`status=passed` 只证明
技术包自洽；报告始终保持 `contract_eligible=false` 和
`buyer_signoff_required=true`，必须另行取得买方外部签署件。

## 声明边界

本包是可复现的空白采购工作底稿，不包含买方数据、真实机器人结果、发票、法律意见、买方验收或已签署合同。模板默认值不会通过采购 Gate。
