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

## 2. 代表性 ADR 详解

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