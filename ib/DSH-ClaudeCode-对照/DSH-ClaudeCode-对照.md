# 独立章节：从 Agent Framework 到 Agent Harness —— DeepSeek Harness 与 Claude Code 架构对照

> 独立成章（作为《企业级 Agent 工程架构实战营》第十篇的扩展专题）。
> 目标：通过深度拆解 **DeepSeek Harness（DSH，DeepSeek Harness）** 与 **Claude Code** 的架构，并与本课程 **DataAgent** 企业级架构对照，
> 理解新一代 Agent Harness 的核心设计取舍、创新价值与适用边界，建立判断未来 Agent Harness 技术演进的架构视角。
> 结论先行：**DSH 代表"通用、可组织、Everything-is-a-Plugin"的面向 HA 的 Harness；Claude Code 代表"产品级、流式、执行闭环"的 Coding Agent；DataAgent 代表"企业级多租户业务 Runtime"。三者边界清晰、互相借鉴。**

---

## 一、为什么从 "Agent Framework" 到 "Agent Harness"

传统 Agent Framework（LangChain/LangGraph 等）的定位是"帮你更容易地编排 Agent"，让开发者以少量代码把一个循环跑起来。
但进入生产后，人们发现真正的难点不再是"会不会跑循环"，而是：

| 问题 | Framework 的答案 | 现实缺口 |
|------|------------------|----------|
| 你是 Agent 的中心还是 Agent 是中心 | 无明确主张 | 需要"Agent 为中心"的 Harness |
| 工具/插件怎么接入 | 写代码注册 | 需要任意可组织、可下发、可复用 |
| 长任务/断点/重试/观测 | 各写各的 | 需要内置的 Runtime/检查点/流式 |
| 组织级：规则/Skill/团队 | 无 | 需要面向用户组织级别的复用 |
| 与 IDE/Git/终端深度集成 | 弱 | Coding Agent 要真实操作仓库 |

**Harness 的核心主张**：把"执行管线、工具接入、上下文字段、检查点、流式、组织资产(规则/Skill/评测)"作为一等公民内置，让使用者可以"驾驭任意 LLM 完成任意复杂任务"，而不是只能跑一个 Demo 循环。这正是"器"（第二篇 09 讲）的工程化落地。

## 二、DSH 核心架构拆解

DeepSeek Harness 以 **`everything is a plugin`** 为组织哲学，把"做一个 Agent"转化为"在 Harness 里声明与组装"，而非手写编排。核心层：

```mermaid
flowchart TB
  subgraph 用户/组织
    Rules[规则(团队级)/Command]
    Skills[Skill 定义/上载/复用]
    Sessions[Session/对话]
  end
  subgraph DSH Kernel
    CM[Context 管理<br/>Agent-Friendly 仓库]
    CT[Tools? 通过插件接入]
    RUN[Run/Pipeline 执行管线]
    CHK[Checkpoint]
    STREAM[Streaming/工具输出]
  end
  subgraph Plugins 生态
    P1[任意命令行/语言工具<br/>Shell/Python/…]
    P2[外部 MCP/服务]
    P3[组织自定义插件]
  end
  Rules---RUN
  Skills---RUN
  Sessions---RUN
  RUN---CT
  RUN---CHK
  STREAM---RUN
  RUN---P1 & P2 & P3
```

设计要点（与普通 Framework 不同之处）：
1. **插件式工具/能力**：`Plugins` 可被动态发现、可组织自定义、可跨项目复用；工具不是"写死在循环 switch 里的函数"。
2. **Avant-Premier 的上下文工程**：`Agent-Friendly Repository`、`Rule 继承与冲突治理` → 把"上下文"从"塞进 Prompt"升级为"系统管理的 Repo/规则"。
3. **检查点与长任务**：执行管线天然支持 checkpoint，长任务可中断/恢复（与本文档 18 讲 Durable Workflow 一致）。
4. **流式与实时反馈**：工具调用、输出、成本实时流式呈现 —— 面向"人盯着 Agent 干活的交互式 Coding"进化。

## 三、Claude Code 架构拆解

Claude Code 是 Anthropic 面向"Coding Agent"的**产品级闭源实现**，它的重心是把"一个超级 Coding 助手"做到极致：

```mermaid
flowchart TB
  U[用户在终端]<-->A[Claude Code CLI]
  A-->IDE[IDE/终端/File Access]
  A-->G[Git/运行时集成]
  A-->CTX[上下文管理/记忆/系统Prompt]
  A-->SSE[Streaming(SSE) 逐 token]
  A-->T[Tools: Shell/Edit/Glob/Grep/Bash]
  A-->CHK[检查点]
  A-->HOOKS[Hooks/权限/允许列表]
```

与 DSH 的差异点：
- **产品目标**：让单个开发者用自然语言把编码任务做完，强调"低摩擦、体验、逐 token 流式、权限粒度"。
- **架构哲学**：以"编辑器 + 终端 + Git + 工具"的执行闭环为中心，把工具调用与停靠/恢复、权限(允许/拒绝列表)做成一等公民。
- **上下文**：用系统化的 context 管理(记忆、会话、相关文件)支撑持续会话；但对"组织级多租户、多 Agent、规则/Skill 治理"不是核心目标。

## 四、DSH vs Claude Code 对照

| 维度 | DeepSeek Harness (DSH) | Claude Code |
|------|------------------------|-------------|
| 定位 | 通用 Agent Harness，Agent 为中心 | 产品级 Coding Agent (CLI) |
| 组织哲学 | `everything is a plugin` | 以执行闭环+体验为中心 |
| 插件/工具 | 一等公民，可组织自定义/复用/动态发现 | 内置工具集(Shell/Edit/Grep)为主，偏封闭 |
| 上下文 | Agent-Friendly Repo/Rule 继承/冲突治理 | 会话记忆+相关文件/系统Prompt |
| 长任务 | Checkpoint/恢复 (Harness 内建) | 检查点/Bash 停靠恢复 |
| 流式 | 有 (工具输出/成本) | 有 (SSE 逐 token) |
| 多租户/组织治理 | 支持(规则/Skill 团队级复用) | 弱(单用户会话) |
| 开放度 | 高(可自建插件) | 中(产品封闭) |
| 适用 | 团队/平台/通用 Run | 个人 Coding 交互 |

**结论**：DSH 更偏"平台/Harness"，Claude Code 更偏"产品/Coding Agent"。二者可互补：在 Claude Code 之上套一个能力更开放的 Harness 抽象，或在 DSH 里接入 Claude Code 作为执行后端。

## 五、DSH vs 本课程 DataAgent

| 维度 | DataAgent(本课程企业级) | DSH |
|------|--------------------------|-----|
| 边界 | 企业级多租户**业务** Runtime | 通用 Coding/Harness |
| 多租户 | 一等公民(tenant/权限/配额/隔离) | 弱(面向单用户/组织资产) |
| 任务 | 经营分析/决策/副作用审批 | 通用复杂任务(Coding 为主) |
| 副作用于/审批 | Human Approval + 幂等 | 权限/允许列表(偏工具) |
| 业务语义 | Metric Registry/经营血缘/证据链 | 无(通用) |
| 评测 | EvalOps/回归门禁/持续进化 | 组织 Skill/Eval 资产 |
| LLM 治理 | LLM Runtime 路由/预算/成本 | 支持但通用 |

**边界结论**：DSH 是"通用 Harness"，DataAgent 是"企业级业务 Agent Runtime"。企业建多租户业务系统应学习 DSH 的 **插件化/组织资产/上下文治理**，但真正承载业务语义、隔离、审批、评测的是类似 DataAgent 的业务 Runtime，两者用统一的 Run/Step/事件模型(见 17 讲)衔接。

## 六、从 DSH 看 Harness 的架构创新（值得企业借鉴）

1. **Everything-is-a-Plugin**：能力以插件形态接入，天然可复用/可治理/可下发 —— 对应本课程第七篇 Capability Architecture 的"形态选型"。
2. **Agent-Friendly Repository + 规则继承/冲突治理**：把"上下文"做成"系统管理的仓库与规则"，而非 Prompt —— 对应第六篇 Context Runtime。
3. **组织级 Skill/Rule/Eval 资产**：个人→团队→组织复用，随模型共同演进 —— 对应第二篇 09 讲"资产飞轮"。

## 七、从 DSH 看未来 Harness 生态

- 从"单 Agent"到"多 Agent + 后台服务"：Harness 将内置多 Agent 编排、显式 Handoff、Parent-Child Run。
- 从"生成内容"到"操作真实世界"：安全、副作用、幂等、审批、审计将内建（DataAgent 已覆盖）。
- Harness 化的 LLM 网关：推理网关(LiteLLM 等)与 Harness 进一步融合。
- 协议化工具接入：MCP 与 Harness 插件接口并存，各取所长。

## 八、课程最终架构讨论：如果今天重新设计 DataAgent

交叉借鉴（落到本项目 `docs/06` 审计的 TOP-12 重构项）：
1. 引入 **推理网关(LiteLLM)** 治理多租户 LLM 成本/配额/回退；
2. 将工具/能力以 **插件 + MCP** 双形态接入，纳入 Capability Registry 动态治理；
3. 更强地复用 **Agent-Friendly Repo/组织 Skill/Team Rule**，建设组织资产飞轮；
4. 用 **统一 Run/Step/Event 模型** 衔接 DSH 通用 Harness 与 DataAgent 业务 Runtime；
5. 深化 **全链路可观测 + SLO**，把"评测+受控进化"做成 Harness 内建能力。

> 一句话总结：**新一代 Harness 的使命，是把"任意 LLM + 任意复杂任务"做成可组织、可复用、可治理、可评测、可持续演进的基础设施 —— 本课程 DataAgent 的企业级业务 Runtime 应当向这个方向持续重构。**