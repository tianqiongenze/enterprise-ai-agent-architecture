# 06 企业级 AI Coding 之道：以人为本的生产观、角色观和责任观

> 所属篇：第二篇（企业级 AI Coding 的道法术器） ｜ 对应代码：`docs/01-SDD规格说明书.md`
> 遵循 **SDD / TDD / DDD / TOGAF** 与软件工程国标约定；全部可离线演示。

---

## 一、本章导语

个人级与团队级 AI Coding 的根本差异在于'有效产出'。本章讲生产观、角色观与责任观。

## 二、教学目标

区分个人级与企业级 AI Coding；理解有效产出公式；建立三观。

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

| 对比 | 个人级 | 企业级 |
|------|--------|--------|
| 目标 | 完成任务 | 可交付资产 |
| 质量来源 | Prompt | 工程系统 |
| 优化 | 省 Token | 优化总交付成本 |
| 迭代 | 一次性 | 复利资产 |

## 五、关键代码（可运行，指向 dataagent 模块）

```python
# 总交付成本 = 模型成本 + Token 成本 + 人理解/修复/运维成本 + 返工成本
print('工程系统决定质量，而不只是 Prompt。')
```

运行方式：

```bash
cd dataagent && PYTHONPATH=src python -m pytest -k security -v
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

| 旧观 | 新观 |
|------|------|
| Prompt 决定质量 | 工程系统决定质量 |
| 节省 Token | 优化总成本 |
| 一次完成 | 复利资产 |
| 追求全自动 | 风险适配自动化 |

## 八、思考题与实战作业

以 DataAgent 的 AutonomyBudget 与人工审批为例，说明'风险适配的自动化'如何落实生产观与责任观。
