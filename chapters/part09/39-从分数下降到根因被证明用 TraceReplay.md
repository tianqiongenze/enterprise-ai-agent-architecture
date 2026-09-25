# 39 从'分数下降'到'根因被证明'：用 Trace、Replay 与 Ablation 完成故障诊断

> 所属篇：第九篇（Agent 评测与受控进化篇） ｜ 对应代码：`dataagent/infra/metrics + tests/fault`
> 遵循 **SDD / TDD / DDD / TOGAF** 与软件工程国标约定；全部可离线演示。

---

## 一、本章导语

把评测失败还原为具体机制问题并通过受控实验证明根因。本章讲评测与 Trace 关联、Failure Taxonomy、症状/直接原因/根因、Replay/Fork/Ablation、Regression Case 沉淀。

## 二、教学目标

把分数下降关联到具体步骤；用 Taxonomy 定位系统层次；用对照实验证明根因。

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

| 方法 | 作用 |
|------|------|
| Trace | 关联到失败步骤 |
| Taxonomy | 失败分类 |
| Replay | 可控重放 |
| Ablation | 分层剔除实验 |
| Regression Case | 防复发 |

## 五、关键代码（可运行，指向 dataagent 模块）

```python
from dataagent.infra.gateway.tools import TenantDataLake, build_dataagent_toolchain
lc = build_dataagent_toolchain(TenantDataLake())
print('用 Trace+Replay+Ablation 定位"错误指标口径"的真实源头')
```

运行方式：

```bash
cd dataagent && PYTHONPATH=src python -m pytest -k fault -v
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

定位错误指标口径来自模型/Context/Tool 还是 Memory 污染，并用对照实验验证修复效果（对齐 tests/fault）。

## 八、思考题与实战作业

为 DataAgent 复现一次'分数下降'，用 Replay+Fork+Ablation 证明根因。
