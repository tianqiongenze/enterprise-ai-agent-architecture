# 28 Tool Contract 与动态工具供给：让 Agent 选对、传对并读懂结果

> 所属篇：第七篇（Agent 工具/技能治理篇） ｜ 对应代码：`dataagent/contracts/tool.py`
> 遵循 **SDD / TDD / DDD / TOGAF** 与软件工程国标约定；全部可离线演示。

---

## 一、本章导语

让模型正确选工具、生成参数并理解结果。本章讲三层 Tool Contract、语义与参数设计、标准结果与错误语义、动态最小工具集。

## 二、教学目标

建立三层 Tool Contract；设计清晰工具语义；用标准结果让 Agent 判断重试/改参/停止；动态供给。

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

| 层 | 内容 |
|----|------|
| 模型理解 | name/desc/params |
| 执行 | 校验+调用 |
| 治理 | 权限/风险/审计/幂等 |

## 五、关键代码（可运行，指向 dataagent 模块）

```python
from dataagent.infra.gateway.tools import build_dataagent_toolchain, TenantDataLake
reg = build_dataagent_toolchain(TenantDataLake())
t = reg.get('query_metric'); print(t.schema_for_model())
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

将指标查询/经营数据查询/Python 分析/报告生成封装为企业级只读工具，并做好最小工具供给。

## 八、思考题与实战作业

对比万能工具/底层 SQL 工具/业务语义工具，说明不同设计对调用成功率与安全的影响。
