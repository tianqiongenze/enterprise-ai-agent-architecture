# 22 经营语义上下文：让 DataAgent 先理解指标，再接触数据

> 所属篇：第六篇（Agent 上下文治理篇） ｜ 对应代码：`dataagent/domain/analytics.py (Metric)`
> 遵循 **SDD / TDD / DDD / TOGAF** 与软件工程国标约定；全部可离线演示。

---

## 一、本章导语

数据库字段不等于业务语义。本章建语义层，让 Agent 先准确理解指标口径、维度与权限，管理别名/粒度/时区/币种，建立 Data Catalog 与血缘，权限先于相关性。

## 二、教学目标

把指标口径沉淀为 Metric Registry；管理术语别名与粒度语义；建立数据血缘；让权限先于相关性。

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

| 资产 | 作用 |
|------|------|
| Metric | 指标权威定义 |
| alias | 自然语言映射 |
| 粒度/时态 | 粒度/时间语义 |
| catalog | 数据血缘 |
| permission | 权限先于相关 |

## 五、关键代码（可运行，指向 dataagent 模块）

```python
from dataagent.domain.analytics import Metric
m = Metric('gmv', '成交总额', '已支付订单金额合计', aliases=('销售额',))
print('销售额→GMV:', m.matches('销售额'))
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

在 DataAgent 中建设 GMV/订单数/客单价/转化率/退款率的 Metric Registry（对齐 domain/analytics.py）。

## 八、思考题与实战作业

为 DataAgent 新增一个指标（退款率），定义口径、别名、维度并验证别名映射。
