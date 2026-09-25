# 21 从 Prompt 拼接到 Context Runtime：先定义每一步决策的信息契约

> 所属篇：第六篇（Agent 上下文治理篇） ｜ 对应代码：`dataagent/infra/context/assembler.py`
> 遵循 **SDD / TDD / DDD / TOGAF** 与软件工程国标约定；全部可离线演示。

---

## 一、本章导语

上下文不等于 Prompt。本章把'大 Prompt 拼接'重构为面向决策步骤、可治理可验证的 Context Runtime。

## 二、教学目标

区分上下文与 Prompt；面向决策组织上下文；建立统一 Context Schema 与 Provider 分层；关键缺失即停。

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

| 元数据 | 说明 |
|--------|------|
| 来源 | 每条内容的来源 |
| 权限 | 角色/租户掩码 |
| 可信度 | trust 等级 |
| 生命周期 | ttl/有效性 |
| 版本 | 内容版本 |

## 五、关键代码（可运行，指向 dataagent 模块）

```python
from dataagent.infra.context.assembler import ContextAssembler, ContextContract
c = ContextContract('planning', required=('metric_registry',))
ass = ContextAssembler()
sl = ass.assemble(step_contract=c)
print('缺失必需项则停止:', c.required_intersection(sl))
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

为 DataAgent 建立规划/查询设计/证据验证/建议生成四套 Decision Context Contract。

## 八、思考题与实战作业

为每个决策步骤定义 must-see / may-see / must-not-see 三类信息。
