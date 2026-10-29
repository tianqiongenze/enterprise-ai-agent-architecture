# 架构决策记录（ADR）与取舍矩阵

> 课程理念：架构师从"给出一个方案"升级为"提出候选方案、明确约束、验证取舍"。本文档记录贯穿项目各个里程碑的架构决策，
> 每个决策都给出 **候选方案 × 取舍矩阵**、**决策依据（证据）** 与 **ADR**。符合软件工程国标对"设计决策记录"的要求。

## 1. 决策索引

| ADR | 主题 | 状态 |
|-----|------|------|
| ADR-001 | LLM 调用从裸 SDK → 统一 LLM Runtime | 已定（第四篇第1课）|
| ADR-002 | 模型选择从"写死模型" → 任务路由 + 回退 | 已定（第四篇第2课）|
| ADR-003 | 一次执行从"重试" → LogicalCall/Attempt 执行模型 | 已定（第四篇第3课）|
| ADR-004 | 并行编排范式：单 Loop vs Workflow vs 混合 | 已定（第五篇第1课）|
| ADR-005 | 开放分析放入 Durable Workflow（审批/恢复/幂等） | 已定（第五篇第4课）|
| ADR-006 | 从单机 while → 可调度 Rust Runtime（端口化） | 已定（第五篇第5课）|
| ADR-007 | 上下文从"Prompt 拼接" → Context Runtime（装配管道） | 已定（第六篇第1课）|
| ADR-008 | Memory 存储分层（关系/向量/Evidence Store） | 已定（第八篇第2课）|
| ADR-009 | 工具能力形态：Tool vs Skill vs Workflow vs MCP | 已定（第七篇第1课）|
| ADR-010 | 评测：单一总分 vs 多维 Scorecard + 硬门槛 | 已定（第九篇第1课）|
| ADR-011 | 发布：全量 vs Shadow / Canary + 回滚 | 已定（第九篇第5课）|
| ADR-012 | 状态机严格化：隐式赋值 → 数据化状态机 + 赋值拦截 | 已定（2026-10-27 对比重构，见 docs/12）|
| ADR-013 | Run 终态所有权：子流程可终结 → Workflow 独占 | 已定（2026-10-27 对比重构，见 docs/12）|
| ADR-014 | 教学资料门禁：人工评审 → validate_chapters.py 五类自检 | 已定（2026-10-27 对比重构，见 docs/12）|
| ADR-015 | deadline 拦截语义：monotonic 注入 + 尝试前检查；同步客户端不强杀 | 已定（2026-10-27 第二轮，见 docs/12 §四 GAP-01）|
| ADR-016 | 覆盖率口径：可选基建适配器（CRDB/ollama/litellm）omit，由环境门控 e2e 验证 | 已定（2026-10-27 第二轮，见 docs/12 §四 GAP-02）|
| ADR-017 | 幂等键契约声明制 + 审批门真实接线（修"死接线"） | 已定（2026-10-27 第三轮，见 docs/12 §四 GAP-09）|
| ADR-018 | 跨 Worker 租约接管：acquire/renew/release/takeover + fencing generation（内存最小实现，生产换存储） | 已定（2026-10-27 第四轮，见 docs/12 §四 GAP-14）|
| ADR-019 | 审批超时 fail-closed：过期≠放行 + 升级链留痕（判定/执行分离） | 已定（2026-10-27 第四轮，见 docs/12 §四 GAP-19）|
| ADR-020 | 观测持久化：JSONL append-only + 幂等去重 + fail-safe（观测故障不阻断业务） | 已定（2026-10-27 第四轮，见 docs/12 §四 GAP-18）|
| ADR-021 | 安全检测语料库化：注入/拒绝词表为版本化数据文件 + 清理样本误报控制 | 已定（2026-10-27 第四轮，见 docs/12 §四 GAP-12）|

## 2. 代表性 ADR 详解

### ADR-012 状态机严格化（数据化状态机 + 赋值拦截）

**背景**：`run.status = X` 为隐式赋值，非法迁移（pending→succeeded、终态复活、挂起直达终态）无任何抵抗；参照工程（dataagent-course）以数据化状态机 + `InvalidStateTransition` 为纪律基线，本仓库缺失该层。

**候选方案**：

| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| a. 提供 transition() 方法，改造全部调用点 | 显式 | 任何新写法可绕过 | ✗ |
| b. `__setattr__` 拦截 + 模块级状态机常量 | 对所有现存/未来代码自动生效 | 魔法感 | ✓ |
| c. 引入第三方状态机库 | 现成 | 迁移表不可评审打印、多一依赖 | ✗ |

**决策**：b。`RUN_STATE_MACHINE`/`STEP_STATE_MACHINE` 为可打印数据常量（构造期自检终态无出边），`__setattr__` 拦截 status 赋值（初始赋值放行、同值幂等放行），`restore()` 经 `object.__setattr__` 显式物化旁路。

**证据（重构实录）**：严格化上线后立即抓出两个真实缺陷并修复——①Harness 越权终结 Run（→ADR-013）；②auto 审批后 `waiting_approval→succeeded` 旁路（→恢复显式回 RUNNING）。12 例新测试钉住（`tests/unit/test_state_machine.py`）。

### ADR-013 Run 终态所有权归 Workflow

**背景**：Harness 作为 workflow 子节点曾自行写 `run.status = SUCCEEDED/FAILED`，与外层 human_gate 的状态迁移冲突（终态保护触发后异常又被兜底 except 吞成业务失败）。

**决策**：Harness 只写 Step/Event 与消费预算，不写 Run 终态；Verifier 失败抛 `VerifierFailedError` 走节点失败路径（Step FAILED → Run FAILED）；workflow 兜底 except 增加终态保护（已终态则 re-raise，不复活）。

### ADR-014 教学资料五类自检门禁

**背景**：旧 42 讲为模板化提纲——索引 40/42 失效、同一占位图复用 81 处、围栏错位、全部低于手册体量，**长期无人发现**。根因：资料没有门禁。

**决策**：`scripts/validate_chapters.py` 五类检查（C1 围栏逐行模拟 / C2 索引双向核对 / C3 十字段结构 / C4 反模板复用计数 / C5 体量下限），事故驱动设计，纳入 CI。

**记录**：42 讲已按统一 10 字段实验手册结构重写并通过全部门禁。

### ADR-006 运行时从 while → 分布式 Runtime

**背景**：经营分析是长任务，且需要审批、恢复、多 Worker 接管。

**候选方案**：

| 方案 | 优点 | 缺点 | 适用 |
|------|------|------|------|
| a. 单进程同步 while | 简单 | 无法支撑长任务/不可恢复/不可扩展 | Demo |
| b. 事件循环 + 内存状态机 | 可回退恢复 | 仍需异步调度 | 中小型 |
| c. Scheduler+Queue+Worker+Lease/Heartbeat | 水平扩展/可接管/持久化 | 复杂度高 | **企业首选（本仓库采用端口契约）** |

**决策**：采用 c 的思路，但在仓库中以 `Protocol（TaskQueue/Worker/RunStore）` + 内存实现落地，满足离线可跑，
生产无缝替换 Celery/Temporal。

**记录**：`contracts/runtime.py` 的 `TaskQueue`/`Worker`/`RunStore`/`Checkpoint`；`infra/runtime/workflow.py` 的 `DurableWorkflowExecutor`。

### ADR-001 LLM 调用统一收敛

**候选方案**：

| 方案 | 效果 | 成本 | 时延 | 风险 | 结论 |
|------|------|------|------|------|------|
| 直接调 SDK | 高 | 高 | — | 与模型强耦合、不可治理 | ✗ |
| 共享 Wrapper | 中 | 中 | — | 无统一契约/无回退/不可观测 | △ |
| 统一 LLM Runtime | 高 | 低 | 低 | 低 | ✓ |

**决策**：统一 LLM Runtime，提供 `LlmClient` 协议 + `ReliableExecutor`（LogicalCall/Attempt、路由、回退、结构化校验、统计）。

## 3. 决策矩阵工具（复现 Course 的 "Decision Matrix / ADR" 机制）

项目用 `docs` + `tests` 作为证据载体：每个变更先补一个失败测试（需求），决策后在 ADR 记录取舍，最后 CI 回归门禁拦截退化。