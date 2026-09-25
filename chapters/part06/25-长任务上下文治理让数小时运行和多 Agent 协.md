# 25 长任务上下文治理：让数小时运行和多 Agent 协作不丢目标、不重做、不漂移

> 所属篇：第六篇（Agent 上下文治理篇） ｜ 对应代码：`dataagent/infra/context + memory`
> 遵循 **SDD / TDD / DDD / TOGAF** 与软件工程国标约定；全部可离线演示。

---

## 一、本章导语

让长任务/中断恢复/多 Agent 一直保持正确目标。本章讲区分 History/State/Checkpoint/Summary、生命周期管理、按用途生成摘要、压缩保留不变量、Artifact Store、协作拓扑、检测 Context Drift。

## 二、教学目标

区分四类过程信息；管理生命周期与不同摘要；定义压缩不变量；设计 Artifact 引用与 Parent-Child Run。

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

| 拓扑 | 说明 |
|------|------|
| 共享完整上下文 | 简单但泄漏多 |
| 显式 Handoff | 受控交接 |
| Artifact 引用 | 大对象外置 |
| Parent-Child Run | 子任务隔离 |

## 五、关键代码（可运行，指向 dataagent 模块）

```python
from dataagent.contracts.runtime import Run, EventType
r = Run(task_type='analysis'); r.add_event(EventType.CHECKPOINT)
cp = r.to_checkpoint(); print('可恢复 checkpoint:', cp.run_id)
```

运行方式：

```bash
cd dataagent && PYTHONPATH=src python -m pytest -k contracts -v
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

完成月度经营分析任务的中断恢复、阶段压缩与库存分析 Child Run 交接。

## 八、思考题与实战作业

设计一次跨多 Agent 交接，验证目标/权限/证据作为受控载荷沿执行图传递。
