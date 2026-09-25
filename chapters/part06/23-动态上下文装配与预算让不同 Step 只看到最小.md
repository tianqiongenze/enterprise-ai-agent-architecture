# 23 动态上下文装配与预算：让不同 Step 只看到最小充分信息

> 所属篇：第六篇（Agent 上下文治理篇） ｜ 对应代码：`dataagent/infra/context/assembler.py (ContextAssembler)`
> 遵循 **SDD / TDD / DDD / TOGAF** 与软件工程国标约定；全部可离线演示。

---

## 一、本章导语

在有限 Token 和成本预算内保留当前决策最需要的信息。本章讲装配管线化、硬过滤/软排序、必需优先、Token Budget 分区、去重冲突、可信压缩与充分性检查。

## 二、教学目标

把上下文装配管线化；保证硬性过滤不被相关性绕过；分区管理预算；调用前做充分性检查。

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

| 能力 | 方法 |
|------|------|
| 管线化 | 装配管道定位错误 |
| 硬过滤 | 权限/租户/有效期 |
| 预算分区 | provenance 配额 |
| 去重 | 冲突处理 |
| 充分性 | required 检查 |

## 五、关键代码（可运行，指向 dataagent 模块）

```python
from dataagent.infra.context.assembler import ContextAssembler
a = ContextAssembler(token_budget=6000)
sl = a.assemble()
print('token 占用:', sl.tokens_used)
```

运行方式：

```bash
cd dataagent && PYTHONPATH=src python -m pytest -k context -v
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

为 DataAgent 的规划/查询/原因分析/建议生成设计动态 Context Profile，并验证硬过滤 > 软排序。

## 八、思考题与实战作业

给 DataAgent 注入跨租户上下文，验证硬性过滤兜底且记录过滤原因。
