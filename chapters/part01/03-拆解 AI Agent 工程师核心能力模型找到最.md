# 03 拆解 AI Agent 工程师核心能力模型：找到最优晋级之路

> 所属篇：第一篇（AI 核心认知篇） ｜ 对应代码：`docs/01-SDD规格说明书.md`
> 遵循 **SDD / TDD / DDD / TOGAF** 与软件工程国标约定；全部可离线演示。

---

## 一、本章导语

从市场招聘需求出发，把企业级 Agent 工程师的能力拆成技术、架构、职业三维画像，并给出 L1→L4 的晋级路径。

## 二、教学目标

建立三维能力画像；理解 L1–L4 分级；从'给方案'到'给候选方案并验证取舍'。

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

| 级别 | 名称 | 负责范围 | 关键交付 |
|------|------|----------|----------|
| L1 | 功能开发 | 既有架构下完成功能 | 可用功能+基础验证 |
| L2 | 业务交付 | 一条 Context/Tool/State/Eval 链路 | 可交付业务 |
| L3 | 系统设计 | Runtime/可靠/安全/成本/可观测 | 架构方案+ADR |
| L4 | 平台演进 | 共享基础设施/工程标准/持续评测 | 平台能力 |

## 五、关键代码（可运行，指向 dataagent 模块）

```python
from dataagent.infra.gateway.llm_runtime import ModelRegistry, Router
reg = ModelRegistry(); rt = Router(reg)
rt.add_route('planning', ['luna', 'default'])  # 候选方案 + 回退
print(rt.decide('planning'))
```

运行方式：

```bash
cd dataagent && PYTHONPATH=src python -m pytest -k llm_runtime -v
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

| 维度 | 技术 | 架构 | 职业 |
|------|------|------|------|
| 覆盖 | 软件工程/LLM/Context/Tool/Memory/Runtime/Eval | 任务建模/控制权/状态/可靠/安全/成本 | 创新/责任/闭环/协作/学习 |
| 产出 | 可运行系统 | 架构方案+ADR | 结果与成长 |

## 八、思考题与实战作业

选出你当前所处级别，列出到更高一级需补的三项能力。第二/九篇训练工程治理，第四/五篇训练运行时与可靠性，第六/七/八篇训练系统抽象。
