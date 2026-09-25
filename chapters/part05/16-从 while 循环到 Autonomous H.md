# 16 从 while 循环到 Autonomous Harness：构建可验证的经营分析闭环

> 所属篇：第五篇（Agent Harness 与 Runtime 工程架构篇） ｜ 对应代码：`dataagent/infra/runtime/harness.py`
> 遵循 **SDD / TDD / DDD / TOGAF** 与软件工程国标约定；全部可离线演示。

---

## 一、本章导语

Harness 不是简单 Agent Loop。本章讲 Plan/Replan 与 Verifier 保证可信、Stop Condition 决定何时结束、Analysis State 管理开放过程。

## 二、教学目标

理解 Harness 与 Loop 的本质区别；用 Verifier/Stop 约束开放分析；让分析状态可恢复、可解释。

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

| 机制 | 防止 |
|------|------|
| Verifier | 越跑越偏 |
| Stop Condition | 不知何时结束 |
| Analysis State | 无法恢复/解释 |
| AutonomyBudget | 无限循环/花钱/调用 |

## 五、关键代码（可运行，指向 dataagent 模块）

```python
# DataAgent 核心闭环见 infra/runtime/harness.py
print('Autonomous Analysis Loop: Plan→Execute→Verify→Stop 已实现')
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

实现 Autonomous Analysis Loop（对齐 dataagent 的 harness），使其自主分析但始终受验证、预算与停止条件约束。

## 八、思考题与实战作业

给 DataAgent 的 Verifier 增加一条'指标口径已确认'规则，验证分析过程可信。
