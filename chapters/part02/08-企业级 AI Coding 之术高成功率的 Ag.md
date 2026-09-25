# 08 企业级 AI Coding 之术：高成功率的 Agent 驾驭与编排技巧

> 所属篇：第二篇（企业级 AI Coding 的道法术器） ｜ 对应代码：`dataagent/infra/runtime/harness.py`
> 遵循 **SDD / TDD / DDD / TOGAF** 与软件工程国标约定；全部可离线演示。

---

## 一、本章导语

方法论之下是技巧。本章讲八个控制变量、高质量 Prompt、高信号密度上下文、任务拆解与节奏、Loop 技巧、Hook/Skill、SubAgent 编排、验证恢复与成本优化。

## 二、教学目标

掌握编排的八个控制变量；在效果/效率/成本/注意力间取舍。

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

| 控制变量 | 作用 |
|----------|------|
| 任务拆解粒度 | 可控性 |
| 上下文信号密度 | 成功率 |
| 执行节奏 | 稳定性 |
| 验证点 | 质量 |
| 恢复策略 | 鲁棒性 |
| 成本上限 | 可行性 |

## 五、关键代码（可运行，指向 dataagent 模块）

```python
from dataagent.infra.runtime.harness import AutonomyBudget
budget = AutonomyBudget(max_steps=6, max_tokens=20000, max_tool_calls=12)
print('继续?', budget.can_continue())
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

用四象限（效果/效率/成本/注意力）评估一次 DataAgent 分析：哪些控制变量可调优，代价是什么？

## 八、思考题与实战作业

调整 DataAgent 的 AutonomyBudget 参数，观察执行路径与成本变化。
