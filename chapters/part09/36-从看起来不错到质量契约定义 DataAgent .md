# 36 从'看起来不错'到质量契约：定义 DataAgent 什么才算真正成功

> 所属篇：第九篇（Agent 评测与受控进化篇） ｜ 对应代码：`dataagent/infra/metrics/eval_ops.py`
> 遵循 **SDD / TDD / DDD / TOGAF** 与软件工程国标约定；全部可离线演示。

---

## 一、本章导语

建立统一质量标准，明确分析任务怎样才算做对、做稳、可进生产。本章讲 Eval Contract、Outcome/Trajectory/System 三层评测、关键行为与安全不变量、软评分与硬门槛。

## 二、教学目标

从业务目标到 Eval Contract；建立三层评测体系；软评分与硬门槛并用。

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

| 层 | 评测对象 |
|----|----------|
| Outcome | 最终答案质量 |
| Trajectory | 执行过程/路径 |
| System | 成本/延迟/安全 |

## 五、关键代码（可运行，指向 dataagent 模块）

```python
from dataagent.infra.metrics.eval_ops import RegressionGate
gate = RegressionGate(min_scores={'code': 0.8})
print('门禁放行/阻断 由回归门禁判定')
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

为'华东区 GMV 下降诊断'定义结果质量、证据链、执行路径、成本与安全标准（对齐 docs/01 M0 基线）。

## 八、思考题与实战作业

定义 DataAgent 的三层 Eval Contract，并给出关键行为与安全不变量。
