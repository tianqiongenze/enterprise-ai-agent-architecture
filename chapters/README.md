# 章节教学资料索引（图文并茂 · 42 讲）

> 每一讲一个 Markdown 教学文档，英文文件名便于链接与版本管理。
> 每讲统一结构：**本章导语 → 教学目标 → 心智模型图 → 核心概念（表格）→ 关键代码（可运行）→ 架构/时序/状态机图 → 候选方案×取舍矩阵 → 思考题与实战作业**。
> 课程贯穿项目代码见 `../dataagent/`，各讲代码片段均可离线运行。

## 第一篇：AI 核心认知篇
| 讲 | 标题 | 文件 |
|----|------|------|
| 01 | 从训推机理理解 LLM：底层心智模型 | `part01/01-LLM-心智模型.md` |
| 02 | 从 Agent 本质到核心范式：Autonomous vs Workflow | `part01/02-Agent-范式.md` |
| 03 | 拆解 AI Agent 工程师核心能力模型 | `part01/03-能力模型.md` |
| 04 | AI Native 团队与个人的知与行 | `part01/04-AI-Native.md` |
| 05 | 从根本讲透 LLM 调优技术：PE/CE/HE/LE/GE | `part01/05-调优技术体系.md` |

## 第二篇：企业级 AI Coding 的道法术器
| 讲 | 标题 | 文件 |
|----|------|------|
| 06 | AI Coding 之道：生产观/角色观/责任观 | `part02/06-AI-Coding-道.md` |
| 07 | AI Coding 之法：把概率生成转化为确定性交付 | `part02/07-AI-Coding-法-SDD.md` |
| 08 | AI Coding 之术：Agent 驾驭与编排技巧 | `part02/08-AI-Coding-术.md` |
| 09 | AI Coding 之器：AI Coding Harness | `part02/09-AI-Coding-器-Harness.md` |

## 第三篇：贯穿实战立项篇
| 讲 | 标题 | 文件 |
|----|------|------|
| 10 | 实战项目立项：多租户零售 DataAgent | `part03/10-项目立项.md` |

## 第四篇：LLM 执行底座篇
| 讲 | 标题 | 文件 |
|----|------|------|
| 11 | 从散落调用到 LLM Runtime | `part04/11-LLM-Runtime.md` |
| 12 | 多模型路由：能力契约与策略路由 | `part04/12-多模型路由.md` |
| 13 | 高并发下可靠的模型执行 | `part04/13-可靠执行.md` |
| 14 | 从能调用到可运营：模型治理体系 | `part04/14-模型治理.md` |

## 第五篇：Agent Harness 与 Runtime 工程架构篇
| 讲 | 标题 | 文件 |
|----|------|------|
| 15 | Agent Runtime 混合架构选型 | `part05/15-Runtime-架构选型.md` |
| 16 | 从 while 循环到 Autonomous Harness | `part05/16-Autonomous-Harness.md` |
| 17 | 从聊天历史到统一执行模型 | `part05/17-统一执行模型.md` |
| 18 | 用 Durable Workflow 收口自主分析 | `part05/18-Durable-Workflow.md` |
| 19 | 从单进程到分布式 Runtime | `part05/19-分布式Runtime.md` |
| 20 | 以故障为教材：跨故障完成任务 | `part05/20-故障工程.md` |

## 第六篇：Agent 上下文治理篇
| 讲 | 标题 | 文件 |
|----|------|------|
| 21 | 从 Prompt 拼接到 Context Runtime | `part06/21-Context-Runtime.md` |
| 22 | 经营语义上下文：先理解指标再接触数据 | `part06/22-经营语义上下文.md` |
| 23 | 动态上下文装配与预算 | `part06/23-动态装配与预算.md` |
| 24 | 企业知识与 Agentic Evidence | `part06/24-企业知识与证据.md` |
| 25 | 长任务上下文治理 | `part06/25-长任务上下文.md` |
| 26 | Context Security 与 ContextOps | `part06/26-Context安全与Ops.md` |

## 第七篇：Agent 工具/技能治理篇
| 讲 | 标题 | 文件 |
|----|------|------|
| 27 | 从 Function Call 到 Capability Architecture | `part07/27-Capability架构.md` |
| 28 | Tool Contract 与动态工具供给 | `part07/28-Tool-Contract.md` |
| 29 | 从 Tool Call 到 Action Runtime | `part07/29-Action-Runtime.md` |
| 30 | Skill Engineering | `part07/30-Skill-Engineering.md` |
| 31 | MCP 与 CapabilityOps | `part07/31-MCP-CapabilityOps.md` |

## 第八篇：Agent Memory 治理篇
| 讲 | 标题 | 文件 |
|----|------|------|
| 32 | 从聊天记录到记忆契约 | `part08/32-记忆契约.md` |
| 33 | 从 Run 事件到可信记忆（写入链路） | `part08/33-记忆写入链路.md` |
| 34 | 从向量 Top-K 到 Recall Contract | `part08/34-Recall-Contract.md` |
| 35 | 从个性化功能到 MemoryOps | `part08/35-MemoryOps.md` |

## 第九篇：Agent 评测与受控进化篇
| 讲 | 标题 | 文件 |
|----|------|------|
| 36 | 从“看起来不错”到质量契约 | `part09/36-质量契约.md` |
| 37 | 从样例集合到可复现基准 | `part09/37-可复现基准.md` |
| 38 | 从“有标准”到“能自动测”：Multi-Grader 与 Batch Runner | `part09/38-Batch-Eval-Runner.md` |
| 39 | 从“分数下降”到“根因被证明” | `part09/39-故障诊断-RootCause.md` |
| 40 | 从离线提升到安全发布：Regression Gate | `part09/40-Regression-Gate.md` |

## 第十篇：完结篇
| 讲 | 标题 | 文件 |
|----|------|------|
| 41 | DataAgent 最终展示与全课程总结 | `part10/41-最终展示-总结.md` |
| 42 | 面向未来：人与 AI 四种关系 / DSH / 演进 | `part10/42-面向未来.md` |

> 全部 42 讲 + 本文档即覆盖大纲所列全部章节主题；每讲末尾的"实战作业"均指向 `../dataagent/` 中的可运行测试。