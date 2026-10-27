# 《企业级 Agent 工程架构实战营》全套课程复现

> 依据课程大纲（`企业级Agent工程架构大纲.pdf`，共 10 篇 / 42 讲）逐篇逐讲复现的教学资料 + 贯穿项目代码仓库。
> 全部内容遵循 **SDD（Specification-Driven Development）、TDD（Test-Driven Development）、DDD（Domain-Driven Design）、TOGAF（企业架构框架）** 以及中国软件工程国标（GB/T）的文档与工程治理约定。

---

## 仓库结构

```
企业级Agent工程架构/
├── README.md                     # 本文件：课程总览 + 快速开始
├── 企业级Agent工程架构大纲.pdf    # 原始课程大纲（来源）
├── 大纲文本.txt                   # 大纲的文本提取（便于检索）
├── docs/
│   ├── 00-TOGAF架构总览.md        # TOGAF 四阶段 × 10 篇映射的总架构视图
│   ├── 01-SDD规格说明书.md         # 规格驱动开发：功能性/非功能性规格 + 验收准则
│   ├── 02-架构决策记录-ADR.md      # 候选方案×取舍矩阵 + ADR 列表
│   ├── 03-架构图集.md              # 系统架构/时序/状态机/领域图（Mermaid）
│   ├── 04-交付物清单.md            # 全部教学资料与项目交付清单
│   ├── 05-部署与运行.md            # 本地离线 / Docker / 演进式部署
│   ├── 06-工业级达标审计与重构建议.md # 联网调研后打分 + TOP-12 重构方向 + 上线门槛
│   ├── 07-部署运行-工业级.md        # 对接真实中间件 + Granian/Pulsar 生产参数 + 踩坑
│   ├── 08-全链路测试报告.md
│   ├── 09-PPT质量评审与优化.md
│   ├── 10-人工测试操作指南.md
│   └── 11-大纲全面复审与缺口闭合.md          # 真实场景功能+性能压测实测、≥1亿行数据生成、k6+Locust
├── dataagent/                     # 贯穿项目：多租户零售 DataAgent 内核（可离线跑）
│   ├── src/dataagent/             # contracts / domain / infra / adapters / app
│   ├── tests/                     # 单元/集成/故障注入 测试（TDD）
│   └── pyproject.toml
├── services/                      # 企业级服务层（Litestar + Granian 全异步 + Pulsar Worker）
│   ├── src/services/              # shared(网关/Provider) / api / worker
│   ├── requirements.txt / pyproject.toml
├── deploy/                        # 生产部署
│   ├── Dockerfile
│   ├── helm/  (Chart.yaml / values.yaml / values-prod.yaml)
│   └── k8s/   (dataagent-api/worker/configmap/pulsar-bootstrap 等)
├── configs/                      # 环境配置(local/prod/worker) + 基础设施端点
├── chapters/                      # 42 讲图文教学资料 + 索引
├── ib/                           # 独立专题章节
│   └── DSH-ClaudeCode-对照/       # DSH vs Claude Code 架构对照（独立章节）
├── tests/                        # 服务层/网关测试 + 压测(Locust)
│   ├── test_services_api.py
│   └── load/locustfile.py
├── scripts/
│   ├── demo.py                    # 端到端演示
│   └── gen_chapters.py
└── .github/workflows/ci.yml       # CI 回归门禁
```

---

## 在线人工测试（局域网浏览器直接用）

**B 端控制台**：`http://10.167.2.175:30080/console`（JWT 登录：admin/admin123 · approver/approve123 · analyst/analyst123）
含：概览/任务中心/**审批中心(HITL)**/租户管理/指标注册中心/模型路由/Capability权限矩阵/Memory管理/发布与灰度/API测试。
异步任务经 Worker（Pulsar 优先/Redis 兜底）真实落库；人工测试用例 TC-01~TC-16 见 `docs/10-人工测试操作指南.md`；
大纲需求覆盖复审见 `docs/11-大纲全面复审与缺口闭合.md`。

## 快速开始（全程离线，无需任何外部 API）

```bash
# 1) 运行测试套件（TDD：单元 + 集成 + 故障注入 + Eval + 回归门禁）
cd dataagent
pip install -r requirements.txt
PYTHONPATH=src python -m pytest -v          # ≈54 项，全部通过

# 2) 运行端到端演示
python ../scripts/demo.py
# 或 CLI
PYTHONPATH=src python -m dataagent "华东区本月 GMV 下滑原因诊断"
```

预期输出：一次从「确认指标口径 → 查询 → 分析 → 结论 → 人工审批」的完整经营决策闭环，
随后演示多租户隔离、模型故障注入后的恢复、只读 SQL 网关拦截、Eval 评分卡 + 回归门禁放行。

> 说明：为达成"完整可测试可部署运行"且离线可演示，本项目内置 **FakeLlmClient**（可编程假模型，支持结构化输出/工具调用/故障注入），
> 而 `LLM Runtime` 的接口契约、路由、重试、回退、预算、沙箱均与真实模型无耦合 —— 接入真实 OpenAI/DeepSeek 只需替换一个 Adapter。

---

## 课程十篇 × 42 讲对照（教学资料详见 `chapters/`）

| 篇 | 主题 | 讲 | 对应代码对象 |
|----|------|-----|--------------|
| 第一篇 | AI 核心认知篇 | 1–5 | 模型契约、Autonomous/Workflow 范式、能力模型 |
| 第二篇 | 企业级 AI Coding 道法术器 | 1–4 | SDD/SPEC、Context-First、Loop、Harness |
| 第三篇 | 贯穿实战立项篇 | 1 | DataAgent 立项、M0 基线、架构选型 |
| 第四篇 | LLM 执行底座篇 | 1–4 | `LLM Runtime`：Routing/Execution/治理 |
| 第五篇 | Agent Harness 与 Runtime 架构篇 | 1–6 | `Harness`+`Workflow`：Run/Step/Approval/故障 |
| 第六篇 | Agent 上下文治理篇 | 1–6 | `ContextAssembler`：Schema/装配/语义/证据/长任务/安全 |
| 第七篇 | Agent 工具/技能治理篇 | 1–5 | `Tool`/`Action`/`Skill`/`MCP`：三层契约、审批、能力地图 |
| 第八篇 | Agent Memory 治理篇 | 1–4 | `Memory`：Pipeline/Recall/MemoryOps |
| 第九篇 | Agent 评测与受控进化篇 | 1–5 | `EvalOps`：三层评测/评分卡/回归门禁/受控发布 |
| 第十篇 | 完结篇 | 1–4 | DataAgent 最终展示、人机四种关系、DSH 与未来 |

---

## 工程方法（贯穿全程）

- **SDD**：`docs/01-SDD规格说明书.md` 定义功能性/非功能性规格与逐讲验收准则；以 *Spec → Contract → Test → Code* 驱动。
- **TDD**：`tests/` 先定义期望，再实现；含故障注入测试（第五篇第6课）、Eval 回归（第九篇）。
- **DDD**：`domain/` 为纯领域逻辑（指标、租户、异常诊断、分析计划），不依赖基础设施；契约层承载统一语言（Ubiquitous Language）。
- **TOGAF**：`docs/00-TOGAF架构总览.md` 将 A（架构愿景）→ B（业务架构）→ C（信息系统架构：数据/应用）→ D（技术架构）与课程的 *认知→AI Coding→Runtime→治理→评测* 五层级闭环映射。
- **软件工程国标（GB/T）**：交付文档按需求、规格、架构、接口、测试、部署、验收分层，记录来源、版本、所有者、生命周期与验收准则。

---

## 核心代码导览（与四十讲机制一一对应）

```text
contracts/model.py    LogicalCall/Attempt —— 一次模型调用的生命周期（第四篇）
contracts/runtime.py  Run/Step/Event/Checkpoint/Approval/Action —— 统一执行模型（第五篇）
contracts/tool.py     Tool 三层契约 + CapabilityRegistry 动态最小工具集（第七篇）
infra/gateway/llm_runtime.py  ModelRegistry/Router/ReliableExecutor —— 多模型路由+可靠执行（第四篇）
infra/runtime/harness.py      Autonomous Analysis Harness + AutonomyBudget/Verifier/Stop（第五篇）
infra/runtime/workflow.py     Durable Workflow + Checkpoint/Resume + Human Approval + 幂等（第五篇）
infra/context/assembler.py    ContextSchema/装配管道/硬过滤/预算分区/充分性检查（第六篇）
infra/memory/memory.py        Memory 写入管道/召回契约/MemoryOps/防投毒（第八篇）
infra/metrics/eval_ops.py     三层评测/Batch Runner/回归门禁/Canary/回滚（第九篇）
infra/security/guards.py      QueryGateway/SQLPolicy/CredentialBroker/注入防护（第二/四/七篇）
domain/analytics.py           指标/租户/归因诊断/分析计划 —— DDD 领域层
```

每个模块头部都标注了它服务课程哪一篇哪一讲，便于教学按章取材。

---

## 演进路径（第三篇"从模块化单体到分布式"）

1. **M0 模块化单体**：`DataAgentContainer` 组合根串联所有能力（当前仓库即为一个可运行的演进基线）。
2. **拆 LLM Runtime**：统一 `ReliableExecutor`，业务代码不再直接依赖模型 SDK。
3. **拆 Agent API + Scheduler + Worker + Sandbox**：Run 持久化 + 队列 + 沙箱接口已就位（`contracts/runtime.TaskQueue/Worker`、`infra/sandbox`）。
4. **补齐治理模块**：Context/Tool/Memory/Skill 均已划分为独立 infra 子模块。
5. **Trace/Eval/多租户/安全/发布治理**：`infra/metrics`、`infra/security`、`tests/fault` 提供全链路支撑。

> 分布式 Scheduler/Queue/Worker（第五篇第5课）以 `Protocol` 端口形式给出契约，本仓库内实现为内存/单进程版本以便离线可运行；
> 生产可无缝替换为 RabbitMQ + Celery / Temporal 等真实分布式底座 —— 这正是"稳定工程对象"的体现。

---

## 许可证 / 合规

本仓库为原创教学复现，与源课程无代码关联；市面上常见框架（LangGraph/Temporal 等）仅作架构对照，未引入依赖。
所有演示数据为虚构的零售订单样例，不含任何真实个人或经营数据。