# 27 从 Function Call 到 Capability Architecture：一项能力应该以什么形态存在？

> 所属篇：第七篇（Agent 工具/技能治理篇） ｜ 对应代码：`dataagent/infra/gateway/tools.py + contracts/tool.py`
> 遵循 **SDD / TDD / DDD / TOGAF** 与软件工程国标约定；全部可离线演示。

---

## 一、本章导语

一个业务能力应封装成 API/Tool/Skill/Workflow/SubAgent/MCP 的哪一种？本章建立统一能力地图，讲形态选型、插件化与服务化、模型决策与系统执行分离、工具粒度、最小模型可见面。

## 二、教学目标

建立能力地图；选型能力形态；分离模型决策与系统执行；控制粒度与最小可见面。

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

| 形态 | 适用 |
|------|------|
| Tool | 单一原子能力 |
| Skill | 领域工序 |
| Workflow | 确定性编排 |
| SubAgent | 独立闭环 |
| MCP | 跨进程/跨团队 |

## 五、关键代码（可运行，指向 dataagent 模块）

```python
from dataagent.contracts.tool import CapabilityRegistry
reg = CapabilityRegistry()
print(reg.visible_for(tenant_id='t', roles={'analyst'}))  # 最小可见面
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

为 DataAgent 完成能力地图选型：数据查询/Python 分析/报告生成/工单创建/预算调整各归为何种形态？

## 八、思考题与实战作业

分析 DataAgent 一个能力：为什么选 Tool 而非 SubAgent？权衡粒度与可见面。
