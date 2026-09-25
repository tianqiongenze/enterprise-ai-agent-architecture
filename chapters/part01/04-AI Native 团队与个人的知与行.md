# 04 AI Native 团队与个人的知与行

> 所属篇：第一篇（AI 核心认知篇） ｜ 对应代码：`dataagent/app/container.py`
> 遵循 **SDD / TDD / DDD / TOGAF** 与软件工程国标约定；全部可离线演示。

---

## 一、本章导语

AI-Enabled 是'现有工作加 AI'，AI Native 是'按 AI 能力重建工作'。本章讲 AI Native 的思维转换、超级个体与超级团队。

## 二、教学目标

区分 AI-Enabled 与 AI Native；完成'完成任务→对结果负责、执行者→定义者、构建者→审查者'的思维转换；理解控制权分配。

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

| 维度 | AI-Enabled | AI Native |
|------|-----------|-----------|
| 思维 | 完成任务 | 对结果负责 |
| 角色 | 执行者 | 定义者/审查者 |
| 资产 | 代码 | 规格+Skill+评测 |
| 协作 | 人→机器 | 人+Agent+确定性系统 |

## 五、关键代码（可运行，指向 dataagent 模块）

```python
from dataagent.app.container import DataAgentContainer, default_seed
c = DataAgentContainer(seed_orders=default_seed())
run = c.analyze('华东区 GMV 下滑')  # 定义问题/审查结果/对结果负责
print(run.status)
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

| 风险等级 | 工具 | 执行者 | 审查者 | 责任人 |
|--------|------|--------|--------|--------|
| 只读 | Agent | Agent | Agent | 人 |
| 低副作用 | Agent | Agent+审批 | 人 | 人 |
| 高副作用 | 禁用 | 人 | 人 | 人 |

## 八、思考题与实战作业

用 DataAgent 的人工审批网关说明控制权分配：为什么高风险的预算调整不能交给 Agent 直接执行？（提示：dataagent/infra/runtime/workflow.py 的 HumanApprovalGate）
