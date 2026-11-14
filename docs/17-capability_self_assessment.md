# 项目 8 项能力定位自评（参照 dataagent-course `capability_self_assessment.md` 惯例）

> **硬规**：8 项**逐项有证据**、**逐项有缺口**、**逐项有行动计划**——"有缺口"列**不得写"无"**，
> 全部无缺口＝没认真做。每行缺口都挂台账编号或 docs 引用，可被质疑。
> 验收命令：`grep -cE '^\| CP-0[1-8] ' docs/17-capability_self_assessment.md` → 期望 **8**（本文件）。

| 能力 | 主责实现 | 证据 | **缺口（不得为"无"）** | 后续行动计划 |
|---|---|---|---|---|
| CP-01 架构判断 | 十篇架构落地 + 范式选型 | `docs/00-TOGAF架构总览.md`（ADM×10 篇映射）、`docs/02` ADR-012~021、`docs/16` 对比打分（参照工程范式矩阵对照） | **范式选型无消融实验背书**：Autonomous/Workflow/混合的选型结论来自课程推演，未在真实负载上做对照 Benchmark（参照 l1_2 的 5 范式矩阵 + l1_5 120 次消融模板未移植） | P2-R8 消融工具落地后，对"是否统一 Durable 收口"跑一次对照并回填 docs/16 |
| CP-02 运行时设计 | 统一执行模型 + 分布式 Runtime | `contracts/runtime.py`（Run/Step/Event/Checkpoint 状态机）、双 Worker + Redis 租约（ADR-018，`lease.py` 6 例测试）、真机双 Worker 一致性（docs/14：审批单 5 张零丢失零重复） | **状态机为代码断言而非数据驱动**：参照 ADR-012 已把迁移表数据化（非法迁移可渲染），本仓库迁移表散在守卫代码里，无法一键渲染迁移矩阵；检查点为 JSONB 整体快照，无增量流 | 迁移表数据化（对齐 ADR-012 形态）+ 提供 `render_transitions()` 渲染命令 |
| CP-03 系统抽象 | 契约族四层 | `contracts/tool.py`（三层 Tool Contract）、`infra/memory/memory.py`（Recall Contract）、`infra/context/assembler.py`（Decision Context Contract）、`contracts/model.py`（模型能力契约） | **契约公共形态未抽基类**（参照自评 CP-03 同款缺口）：四份契约的 required/validate/define 各自实现，无 lint 规则禁止复制粘贴 | 抽 `Contract` 基类（required+validate），加一条自定义 lint/测试钉住"不得自行定义 required" |
| CP-04 工程治理 | 台账 + 门禁 + RBAC/配额 | `docs/12` GAP-01~36（34 关闭/2 移交）、`validate_chapters` 六类门禁、JWT+RBAC 四角色（`services/api/auth.py`）、租户 quota_rps 落库 | **治理门禁未合流**：validate_chapters（资料）、acceptance.py（本仓待建 R6）、CI pytest 三套各自为政，无一条命令全查；租约/审批两套治理规则没有统一的 ops runbook | P1-R6 acceptance.py 合流 + 一页 ops runbook（审批超时/租约过期/能力下线三流程） |
| CP-05 可靠性设计 | 故障注入 + 真机战果 | `tests/fault/test_fault_injection.py`、docs/14 真机 13 项缺陷战果表（granian 参数/Lua None/DLQ API/ack 绑定/预算带病成功…）、GAP-30 fail-closed 钉住（`tests/defect_regressions.py`） | **跨进程故障恢复未系统化注入**：kill -9 Worker 中途、CRDB 闸门饱和叠加审批挂起等复合故障无自动化场景；缺陷回归墙（R2）刚建，覆盖 9 例尚薄 | 复合故障场景脚本化（chaos 套件）：kill -9 + 闸门饱和 + 双 Worker 抢占三合一 |
| CP-06 可观测诊断 | Trace/事件流/观测记录 | `infra/observability/recorder.py`（JSONL 三流）、`/metrics` Prometheus、Run Timeline（docs/10 TC-02）、成本统计（`stats.input_tokens`） | **成本无按任务类型归集**：只有总量累加，答不了"哪类任务贵"（参照同款缺口）；无消融对比视图 | P2-R11 stats 加 task_type 维度 + dashboard 分组；R8 消融产出对比视图 |
| CP-07 生产演进 | 评测/门禁/灰度/回滚 | `infra/metrics/eval_ops.py`（canary 自动停/kill switch/指纹绑定，GAP-11）、`RegressionGate` + CI、Dataset v2 三终态反例、docs/15 压测基线 | **灰度比例未接到真实分流面**：canary_pct 落库但 API 无按租户灰度路由实现；评测集 v2 反例未接 CI 定时跑 | 网关按租户×canary_pct 分流（读 release_state）+ 评测集 v2 进 CI nightly |
| CP-08 交付评审 | 演示 + 验收 + 评审材料 | docs/10 人工测试 TC-01~16、docs/14 真机验收、docs/15 压测、LAN E2E 可复现命令、B 端控制台 10 页 | **未做跨人终期评审**（参照自评同款）：本表与 docs/16 均为自评，无独立评审人签核；评审判据未与产物逐条绑定 | 组织一次跨人评审：用 docs/16 打分表作为判据基线，3 人独立打分取 2/3 一致 |

## 四条读法（同参照工程惯例）

1. **缺口高度集中**：教学法（消融/评审）与"数据驱动"（状态机/成本归集）两类，均为可执行项而非空话。
2. **每条缺口都挂了编号动作**：R1~R11（docs/16 §四）或新开 GAP 编号，不落地不销账。
3. **本表随轮次更新**：缺口列禁止演化为"已完成"；已完成的缺口移入证据列并注明轮次。
4. **自评不替代评审**（CP-08）：本表是评审输入，不是评审结论。

## 缺口分布统计

| 缺口类型 | 涉及能力 | 计数 |
|---|---|---|
| 消融/Benchmark 缺失 | CP-01、CP-06 | 2 |
| 数据驱动化不足 | CP-02、CP-03 | 2 |
| 治理合流/自动化不足 | CP-04、CP-07 | 2 |
| 评审纪律 | CP-08 | 1 |
| 故障注入厚度 | CP-05 | 1 |
| **合计** | 8 项能力 | **8 项全部有缺口** |
