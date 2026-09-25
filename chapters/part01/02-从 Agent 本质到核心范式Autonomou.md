# 02 从 Agent 本质到核心范式：Autonomous Agent 与 Workflow Agent

> 所属篇：第一篇（AI 核心认知篇） ｜ 对应代码：`dataagent/contracts/runtime.py (Run/Step)`
> 遵循 **SDD / TDD / DDD / TOGAF** 与软件工程国标约定；全部可离线演示。

---

## 一、本章导语

Agent 不是一种单一样式。本章厘清 Autonomous 与 Workflow 两大根本范式及其子范式，并给出企业级混合架构选型的判断框架。

## 二、教学目标

区分 ReAct / Plan-and-Execute / Prompt Chaining / Routing / Parallelization / Orchestrator-Workers / Evaluator-optimizer；理解 Autonomous 与 Workflow 的适用与代价；能据业务特性选型混合架构。

## 三、心智模型图

```mermaid
flowchart LR
  Goal[业务目标] --> Spec[规格 SPEC]
  Spec --> Contract[契约 Contract]
  Contract --> Test[测试 TDD]
  Test --> Loop[受控执行 Loop]
  Loop --> Verify[独立验证 Verify]
  Verify --> Deliver[渐进交付]


## 四、核心概念拆解

| 范式 | 机制 | 优点 | 代价 | 场景 |
|------|------|------|------|------|
| ReAct | 决策-行动-观察循环 | 灵活 | 漂移/成本 | 开放式问题 |
| Plan-and-Execute | 先规划后执行 | 全局可控 | 计划过时 | 长任务 |
| Prompt Chaining | 管道串联 | 简单 | 不灵活 | 固定流水线 |
| Routing | 条件分派 | 精确 | 分支枚举 | 分类任务 |
| Parallelization | 并行 | 快 | 合并成本 | 子任务独立 |
| Orchestrator-Workers | 编排-执行 | 可扩展 | 编排复杂 | 多角色 |
| Evaluator-optimizer | 生成-评估-优化 | 质量高 | 多次调用 | 可评判任务 |

## 五、关键代码（可运行，指向 dataagent 模块）

```python
from dataagent.contracts.runtime import Run, RunStatus
r = Run(task_type='analysis')
r.status = RunStatus.RUNNING
print(r.run_id, r.status)  # 各范式统一由 Run/Step/事件模型承载
```

运行方式：

```bash
cd dataagent && PYTHONPATH=src python -m pytest -k contracts -v
```

## 六、架构 / 时序 / 状态机图

None

## 七、候选方案 × 取舍矩阵

| 维度 | Autonomous | Workflow | 混合 |
|------|-----------|----------|------|
| 灵活度 | 高 | 低 | 中 |
| 可控性 | 低 | 高 | 中 |
| 成本 | 高 | 低 | 中 |
| 适用 | 开放/探索 | 固定/合规 | 企业生产 |

## 八、思考题与实战作业

企业应优先用 Workflow 承载确定性环节、用 Autonomous 承载探索环节，二者以统一执行模型（Run/Step）编排。请结合 DataAgent 分析任务说明哪些环节该自主、哪些该流程化。
