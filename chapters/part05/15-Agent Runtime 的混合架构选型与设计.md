# 15 Agent Runtime 的混合架构选型与设计：取长补短

> 所属篇：第五篇（Agent Harness 与 Runtime 工程架构篇） ｜ 对应代码：`dataagent/infra/runtime/workflow.py`
> 遵循 **SDD / TDD / DDD / TOGAF** 与软件工程国标约定；全部可离线演示。

---

## 一、本章导语

一条经营分析需求要被拆成模型、代码与人工协同完成。本章讲 Task Contract、执行范式选型、控制权矩阵、Graph Engineering、Autonomy Budget。

## 二、教学目标

让业务需求变成可执行任务（Task Contract）；选择单 Loop/固定 Workflow/动态 Graph/混合；建立控制权矩阵与自主性预算。

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

| 范式 | 何时选 |
|------|--------|
| 单 Loop | 简单探索 |
| 固定 Workflow | 确定性/合规 |
| 动态 Graph | 复杂拓扑 |
| 多 Agent Graph | 多角色 |
| 混合 | 企业生产 |

## 五、关键代码（可运行，指向 dataagent 模块）

```python
from dataagent.infra.runtime.harness import AutonomyBudget
print(AB := AutonomyBudget(max_steps=5), '自主性预算可硬性停止')
```

运行方式：

```bash
cd dataagent && PYTHONPATH=src python -m pytest -k integration -v
```

## 六、架构 / 时序 / 状态机图

```mermaid
flowchart LR
  Goal[业务目标] --> Spec[规格 SPEC]
  Spec --> Contract[契约 Contract]
  Contract --> Test[测试 TDD]
  Test --> Loop[受控执行 Loop]
  Loop --> Verify[独立验证 Verify]
  Verify --> Deliver[渐进交付]


## 七、候选方案 × 取舍矩阵

控制权矩阵 / 自主性预算 / 人工介入边界 在 DataAgent 中哪里体现？（提示：审批网关 + AutonomyBudget + 只读工具）

## 八、思考题与实战作业

设计 DataAgent 经营分析主链的控制权矩阵，建立后续所有 Runtime 的执行骨架。
