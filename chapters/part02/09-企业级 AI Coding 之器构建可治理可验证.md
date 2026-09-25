# 09 企业级 AI Coding 之器：构建可治理、可验证、可复用的 AI Coding Harness

> 所属篇：第二篇（企业级 AI Coding 的道法术器） ｜ 对应代码：`dataagent/infra + app/container.py`
> 遵循 **SDD / TDD / DDD / TOGAF** 与软件工程国标约定；全部可离线演示。

---

## 一、本章导语

'器'是把经验、流程、制度外置为基础设施。本章讲 Context System、Sandbox、Workflow/Hook/Skill 编排、Observability、Skill/规则/评测资产平台、搭建最小可用 Harness。

## 二、教学目标

把 Coding 从工具升级为系统；理解资产边界与升级机制；搭建最小可用 AI Coding Harness。

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

| 资产 | 边界 | 版本/所有者 | 升级机制 |
|------|------|------------|----------|
| Prompt | 单条 | 无序 | Badcase 回流 |
| Rule | 规则 | 版本化 | 资产平台 |
| Skill | 能力 | 版本化 | 持续评测 |
| Workflow | 编排 | 版本化 | 生命周期 |
| Eval | 质量标准 | 版本化 | 回归门禁 |

## 五、关键代码（可运行，指向 dataagent 模块）

```python
from dataagent.app.container import DataAgentContainer, default_seed
c = DataAgentContainer(seed_orders=default_seed())
run = c.analyze('华东区 GMV 下滑')
print(len(run.events), '个事件')  # 组合 Builder/Reviewer/Hook/StopGate 的可治理 Harness
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

为一个真实项目（Agent-Friendly Repository、任务/上下文/工具权限/执行环境、Builder/Reviewer/Hook/Stop Gate）设计最小可用 Harness。

## 八、思考题与实战作业

结合 docs/05 部署与 scripts/demo.py，说明一套可治理的 Harness 由哪些资产组成。
