# Q-TAIL-MVP Multi-Agent Project Build

**Time**: 2026-04-20 18:30 GMT+8
**Objective**: Build Q-TAIL-MVP multi-agent system based on PDF specification document

## Key Decisions & Reasoning

1. **Project Location**: `/Users/avalok/.openclaw/workspace/Q-TAIL-MVP/` (new directory, no modification to existing projects)
2. **Architecture**: 5-agent system + Orchestrator pattern per PDF specification
3. **Data**: Copied quantum CSV data from `/Users/avalok/work/Q-TAIL-MVP/data/`
4. **PDF Extraction**: Used OCR (pytesseract + pdf2image) as PDF was image-based

## Project Structure
```
Q-TAIL-MVP/
├── main.py                          # Orchestrator (主控协调器)
├── README.md                        # 项目说明
├── config/default.yaml              # 配置文件
├── agents/                          # 5个智能体
│   ├── quantum_source_agent.py      # 量子源适配器
│   ├── semantic_mapper_agent.py     # 语义映射器
│   ├── quantum_scheduler_agent.py   # 量子调度器
│   ├── training_agent.py            # 训练Agent
│   └── evaluation_agent.py          # 评估Agent
├── core/                            # 核心库
│   ├── quantum_prior.py             # 量子先验引擎 (PT分布, CDF, 验证)
│   ├── semantic_mapper.py           # 语义映射 (tail score, 分类)
│   ├── scheduler.py                 # 量子调度器 (6种策略)
│   └── metrics.py                   # 评估指标 (Head/Tail/CVaR@20)
├── data/                            # 量子CSV数据 (3个源文件)
└── results/                         # 运行结果JSON
```

## Core Formula Implementation
`q = (1-η)b + ηPs` — implemented in `core/scheduler.py`
- 6 scheduling strategies: uniform, empirical, invfreq, pt-rank, pt-ot, pt-schedule
- Rank matching: maps PT distribution tail structure to task space
- Dynamic η scheduling support

## Pipeline Validation
- Full 5-step pipeline runs successfully (0.9s for 5000 episodes in simulation mode)
- Quantum source: 3 CSV files loaded, CV≈0.60-0.63, KS≈0.26 (consistent with PT distribution)
- Semantic mapping: MT10 classified as 4 head / 3 medium / 3 tail tasks
- Scheduling: All 6 strategies produce valid sampling distributions
- Training: Simulation mode validated (MuJoCo-free)
- Evaluation: Strategy comparison table generated correctly

## Notes
- Meta-World integration ready but requires MuJoCo for real training
- `simulation_mode=True` by default for testing without MuJoCo
- Metaworld source code available at `/Users/avalok/work/Q-TAIL-MVP/Metaworld/`
