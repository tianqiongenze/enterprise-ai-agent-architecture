# SDD 规格说明书 —— 企业级多租户零售 DataAgent

> 规格驱动开发（Specification-Driven Development）：先定义"需求→规格→契约→验收准则"，再交由测试驱动实现（TDD）。
> 本文档按软件工程国标（GB/T 8567、GB/T 9385 等）对"需求/规格"的约定编写。

## 1. 范围

面向品牌商家 / 零售企业，提供**多租户**的经营数据分析、异常诊断、决策建议与受控业务执行（DataAgent）。
与课程第三篇"贯穿实战立项篇"对应，是后续第四至第九篇所有能力与代码的验收锚点。

## 2. 功能需求（FR）

| 编号 | 需求 | 对应代码 / 模块 | 验收准则（可执行） |
|------|------|----------------|-------------------|
| FR1 | 接受用户经营问题，生成多步骤分析计划 | `domain.analytics.AnalysisPlan`、`infra.runtime.harness` | Run 含 `plan/query/analyze/conclusion` 节点 |
| FR2 | 按租户隔离查询订单/指标 | `infra.gateway.tools.TenantDataLake`、`QueryGateway` | 不同租户 `query_metric` 返回不同 GMV |
| FR3 | 指标口径统一（别名映射） | `domain.analytics.Metric` | `GMV`/`销售额` 映射到同一指标 |
| FR4 | 数据查询只读 + SQL 安全 | `infra.security.guards.SQLPolicy` | 非 SELECT / 含 `;` / DDL 被拦截 |
| FR5 | 行/列级权限 | `TenancyContext.row_filter/col_filter` | 只返回 `region='华东'` 且仅允许字段 |
| FR6 | 异常归因诊断（GMV 下滑） | `RetailDiagnosisService` | 输出触发因子、原因、影响、证据、建议 |
| FR7 | 高风险副作用经人工审批 | `infra.runtime.workflow.HumanApprovalGate` | `approval_requested/resolved` 事件存在 |
| FR8 | 副作用幂等 | `IdempotencyStore` | 同一幂等键只执行一次 |
| FR9 | 上下文按决策步骤装配、缺失即停 | `ContextAssembler + ContextContract` | 缺 `metric_registry` 触发 `__missing_required__` |
| FR10 | 长期记忆写入/召回/删除，防投毒 | `infra.memory` | 拒绝含"临时结论/原始查询/模型推测"，租户隔离 |
| FR11 | 故障注入下仍完成任务 | `tests/fault` | 模型多次失败后重试成功，Run 为 succeeded |
| FR12 | 评测评分卡 + 回归门禁 | `infra.metrics.eval_ops` | `RegressionGate` 各指标达标 |
| FR13 | 模型调用统一、可路由、可观测 | `infra.gateway.llm_runtime` | 按任务路由，统计/回退/重试生效 |
| FR14 | 工具三层契约 + 动态最小工具集 | `contracts.tool` | HIGH 风险工具对 analyst 不可见 |

## 3. 非功能需求（NFR）

| 编号 | 维度 | 准则 |
|------|------|------|
| NFR1 | 可运行性 | 全离线运行，无任何外部 API/凭据 |
| NFR2 | 可测试性 | `pytest` 全绿（单元/集成/故障注入） |
| NFR3 | 一致性 | 持久化用同一套 `Run/Checkpoint` 状态机 |
| NFR4 | 可追溯 | 每次模型/工具调用写入 Run Timeline 与审计 |
| NFR5 | 可演进 | 所有基础设施通过 `Protocol` 端口抽象，可替换 |
| NFR6 | 安全 | 只读网关、短期凭据、注入防护、租户隔离测试 |
| NFR7 | 成本 | `LogicalCall` 记录 token 与预算（`AutonomyBudget`） |

## 4. M0 质量基线（第三篇第1课）

从 **Outcome / Trajectory / System** 三个层次定义初始成功标准：

- **Outcome**：诊断结论正确、证据链完整、给出可执行建议。
- **Trajectory**：执行轨迹（`Run Timeline`）完整可回放，被过滤/缺失上下文有记录。
- **System**：成本（token）有界、时延可测、安全性（租户/只读/审批）通过。

首批关键 Eval Case：经营诊断、跨租户访问、故障恢复、审批拒绝、上下文缺失停止执行。

## 5. 验收流程（SDD + TDD 闭环）

```text
需求/规格(本文档) → 契约(tests 先写) → 实现 → 测试通过(Regressosomal) → ADR 记录 → 演示/部署
```