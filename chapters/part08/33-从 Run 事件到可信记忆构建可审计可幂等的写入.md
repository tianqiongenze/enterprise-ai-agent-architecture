# 33 从 Run 事件到可信记忆：构建可审计、可幂等的写入链路

> 所属篇：第八篇（Agent Memory 治理篇） ｜ 对应代码：`dataagent/infra/memory/memory.py (MemoryWritePipeline)`
> 遵循 **SDD / TDD / DDD / TOGAF** 与软件工程国标约定；全部可离线演示。

---

## 一、本章导语

把任务中产生的候选信息经验证、去重、冲突处理后安全写入。本章讲写入触发机制、Memory Write Pipeline（提取-标准化-校验-策略-提交）、Schema/Scope、幂等与重复治理、冲突版本失效。

## 二、教学目标

建立受控的写入链路；用 Scope 归属记忆；幂等去重；版本与冲突治理。

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

| 步骤 | 作用 |
|------|------|
| 提取 | 从 Run 事件 |
| 标准化 | 统一 schema |
| 校验 | 拒绝脏数据 |
| 策略 | allowed/confirm/denied |
| 提交 | 幂等写入 |

## 五、关键代码（可运行，指向 dataagent 模块）

```python
from dataagent.infra.memory.memory import MemoryWritePipeline, InMemoryMemoryStore, MemoryPolicyEngine
pipe = MemoryWritePipeline(InMemoryMemoryStore(), MemoryPolicyEngine())
print(pipe.write(tenant_id='t', owner='u', key='pref',
                 content='用户偏好：周报柱状图')[0])
```

运行方式：

```bash
cd dataagent && PYTHONPATH=src python -m pytest -k memory -v
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

写入报告偏好和任务引用，拒绝写临时结论/原始查询/模型推测（对齐 tests/unit/test_memory.py）。

## 八、思考题与实战作业

为 DataAgent 实现一次'写入同 key 记忆'的版本升级，保证幂等。
