# 19 从单进程到分布式 Runtime：让长任务可调度、可接管、可隔离

> 所属篇：第五篇（Agent Harness 与 Runtime 工程架构篇） ｜ 对应代码：`dataagent/contracts/runtime.py + infra/sandbox`
> 遵循 **SDD / TDD / DDD / TOGAF** 与软件工程国标约定；全部可离线演示。

---

## 一、本章导语

将 DataAgent 演进为支持异步调度、水平扩展与故障接管的分布式 Runtime，讲 Scheduler/Queue/Worker、Lease/Heartbeat、多租户资源治理。

## 二、教学目标

理解为什么不能同步执行；用 Scheduler/Queue/Worker 调度任务；用 Lease/Heartbeat 避免重复执行；保证多租户公平。

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

| 组件 | 职责 |
|------|------|
| Scheduler | 决定何时执行 |
| Queue | 待办缓冲 |
| Worker | 实际执行/接管 |
| Lease/Heartbeat | 并发一致 |
| 租户配额 | 公平隔离 |

## 五、关键代码（可运行，指向 dataagent 模块）

```python
from dataagent.contracts.runtime import TaskQueue
# 以 Protocol 端口抽象；生产可替换 Celery/Temporal
print('TaskQueue/Worker 端口已定义（见 contracts/runtime.py）')
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

完成 Runtime 分布式部署（doc/05 演进 M2–M4）：从单进程到可调度、可接管、可隔离。

## 八、思考题与实战作业

把 RunStore 替换为真实队列实现，验证任务可被不同 Worker 接管。
