# 18 用 Durable Workflow 收口自主分析：实现中断、审批与副作用闭环

> 所属篇：第五篇（Agent Harness 与 Runtime 工程架构篇） ｜ 对应代码：`dataagent/infra/runtime/workflow.py`
> 遵循 **SDD / TDD / DDD / TOGAF** 与软件工程国标约定；全部可离线演示。

---

## 一、本章导语

为什么开放分析必须放进 Workflow？因为真实业务需要审批、中断恢复与安全执行。本章讲 Workflow Shell、Checkpoint/Resume、Human Approval、副作用幂等。

## 二、教学目标

把 Autonomous 收进可恢复的工作流；实现人工审批与副作用幂等；完成受控的经营决策闭环。

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

| 能力 | 方法 |
|------|------|
| 中断 | Checkpoint+Resume |
| 审批 | Human Approval Gate |
| 副作用 | 幂等（幂等键） |
| 追踪 | Run Timeline |

## 五、关键代码（可运行，指向 dataagent 模块）

```python
from dataagent.infra.runtime.workflow import IdempotencyStore
idem = IdempotencyStore()
print(idem.try_mark('budget:2026-09-25:CN'), idem.try_mark('budget:2026-09-25:CN'))
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

完成'预算审批执行流程'实战：预览→审批→受控执行→结果验证闭环，用幂等键防止重复执行。

## 八、思考题与实战作业

把 DataAgent 的预算调整动作接入人工审批，检验审批拒绝时 Run 状态与事件。
