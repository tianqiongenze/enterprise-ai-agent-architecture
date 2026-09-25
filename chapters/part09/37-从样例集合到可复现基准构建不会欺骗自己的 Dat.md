# 37 从样例集合到可复现基准：构建不会欺骗自己的 Dataset 与 Fixture

> 所属篇：第九篇（Agent 评测与受控进化篇） ｜ 对应代码：`dataagent/infra/metrics/eval_ops.py (snapshot_fixture)`
> 遵循 **SDD / TDD / DDD / TOGAF** 与软件工程国标约定；全部可离线演示。

---

## 一、本章导语

贴近真实业务且环境固定的评测基准。本章讲从真实业务构建 Task Taxonomy、企业级 Eval Case 设计、Fixture 与环境快照、版本元组与结果归因、评测集分层治理。

## 二、教学目标

从真实业务构建评测集；用 Fixture 保证可复现；用版本元组归因结果。

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
| Task Taxonomy | 覆盖生产长尾 |
| Eval Case | 开放任务验收 |
| Fixture | 环境快照 |
| 版本元组 | 结果归因 |

## 五、关键代码（可运行，指向 dataagent 模块）

```python
from dataagent.infra.metrics.eval_ops import snapshot_fixture
print(snapshot_fixture(model='luna', prompt_version='v2',
                      context_version='v1', tool_set='ro', tenant='ten_a'))
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

构建 DataAgent 基准集：经营诊断/数据缺失/工具故障/跨租户访问/审批拒绝等核心 Case（对齐 docs/01）。

## 八、思考题与实战作业

给 DataAgent 设计 5 个不具唯一标准答案的开放 Case，并定义其验收准则。
