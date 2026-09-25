# 11 从散落调用到 LLM Runtime：建立稳定而不失真的模型执行边界

> 所属篇：第四篇（LLM 执行底座篇） ｜ 对应代码：`dataagent/infra/gateway/llm_runtime.py`
> 遵循 **SDD / TDD / DDD / TOGAF** 与软件工程国标约定；全部可离线演示。

---

## 一、本章导语

为什么不能在业务代码里直接调模型 SDK？本章讲 LLM Runtime 的定位与职责边界、统一契约、能力差异保留、分层结构，并用 DataAgent 对比三种方案。

## 二、教学目标

理解为什么需要统一模型执行边界；掌握统一契约+Provider Adapter；掌握 Runtime 分层（Registry/Routing/Execution/Observability）。

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

| 层 | 职责 |
|----|------|
| Registry | 模型能力注册/别名 |
| Routing | 按任务选型+回退 |
| Execution | LogicalCall/Attempt/重试 |
| Observability | 统计/成本/审计 |

## 五、关键代码（可运行，指向 dataagent 模块）

```python
from dataagent.infra.gateway.llm_runtime import ModelRegistry, Router
from dataagent.adapters.llm.fake_client import FakeLlmClient
reg = ModelRegistry(); rt = Router(reg)
rt.add_route('planning', ['luna', 'default'])  # 逻辑/物理解耦
client = FakeLlmClient(); print('统一 Runtime 就绪')
```

运行方式：

```bash
cd dataagent && PYTHONPATH=src python -m pytest -k llm_runtime -v
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

| 方案 | 效果 | 成本 | 时延 | 风险 | 结论 |
|------|------|------|------|------|------|
| 直接调 SDK | 高 | 高 | — | 与模型强耦合 | ✗ |
| 共享 Wrapper | 中 | 中 | — | 无统一契约/不可观测 | △ |
| 统一 Runtime | 高 | 低 | 低 | 低 | ✓ |

## 八、思考题与实战作业

对比直接 SDK/共享 Wrapper/统一 Runtime 三种方案（ADR-001），把 DataAgent 中分散调用统一收敛为模型执行入口。
