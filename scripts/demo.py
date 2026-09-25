#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""DataAgent 端到端演示脚本 —— 用于课程讲解与验收 (第十篇)。

展示：
1. 一次完整经营分析与决策链路（Durable Workflow 包裹 Autonomous Harness）
2. 多租户隔离与数据权限
3. 故障注入与恢复（LLM 上游反复故障后仍能完成任务）
4. Eval 评分卡 / CI 回归门禁
5. 上下文治理 / Memory / 工具 / 安全 机制自检

全程离线运行，无需任何外部 API。
"""
from __future__ import annotations

import os
import sys

# 允许在任意位置执行
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dataagent", "src"))


def demo_basic():
    from dataagent.app.container import DataAgentContainer, default_seed

    c = DataAgentContainer(seed_orders=default_seed())
    run = c.analyze("华东区本月 GMV 下滑原因诊断")
    print("\n[1] 经营诊断链路")
    print(f"   Run={run.run_id}  状态={run.status.value}")
    for s in run.steps:
        o = {k: v for k, v in s.output.items()}
        print(f"   - {s.name:22s} [{s.status.value}] {o}")
    print(f"   事件流长度={len(run.events)}  (可回放/可审计)")
    return c


def demo_multitenant(c):
    from dataagent.app.container import default_seed

    print("\n[2] 多租户隔离")
    for t in ("ten_a", "ten_b"):
        m = c.tools.get("query_metric").invoke({"tenant_id": t}, tenant_id=t)
        print(f"   {t}: GMV={m.value['gmv']}  单量={m.value['order_count']}")


def demo_fault(c):
    from dataagent.infra.security.guards import SQLPolicy, QueryGateway, TenancyContext

    print("\n[3] 故障注入与只读 SQL 网关")
    c.client.fail_times = 2
    run = c.analyze("华东区退货率分析")
    print(f"   注入 2 次模型故障后仍成功: 状态={run.status.value}, 调用次数={c.client.call_count}")
    gw = QueryGateway(SQLPolicy())
    ctx = TenancyContext(tenant_id="ten_a", user_id="u1", roles={"analyst"}, row_filter={"region": "华东"})
    bad = gw.execute(ctx, lambda s: [], "DELETE FROM orders")
    print(f"   SQL 网关拦截 'DELETE': {bad}")


def demo_eval(c):
    from dataagent.infra.metrics.eval_ops import BatchEvalRunner, RegressionGate, code_grader

    print("\n[4] Eval 评分卡 + CI 回归门禁")
    run = c.analyze("华东区 GMV 下滑")
    runner = BatchEvalRunner([code_grader(lambda r: r.status.value == "succeeded" and len(r.events) > 5)])
    report = runner.evaluate([(run, {})])
    print(report.summary())
    gate = RegressionGate(min_scores={"code": 0.8})
    ok, viol = gate.evaluate(report)
    print(f"   回归门禁: {'PASS ✓' if ok else 'BLOCK ✗' + str(viol)}")


def demo_governance(c):
    from dataagent.infra.memory.memory import MemoryScope, default_memory_validate

    print("\n[5] 上下文/Memory/工具/安全 机制自检")
    # Context 充分性
    from dataagent.infra.context.assembler import ContextContract
    sl = c.ctx.assemble(step_contract=ContextContract("planning", required=("metric_registry",)))
    ok, msg = default_memory_validate("用户偏好：周报要柱状图")
    print(f"   Context 充分性(规划需要指标口径): {'满足' if not sl.filtered or not any(k=='__missing_required__' for k,_ in sl.filtered) else '缺失'}")
    print(f"   Memory 策略: 写入偏好 → {'允许' if ok else msg}")


if __name__ == "__main__":
    print("=" * 62)
    print("DataAgent —— 企业级多租户零售经营分析与决策 Agent (课程贯穿项目)")
    print("=" * 62)
    c = demo_basic()
    demo_multitenant(c)
    demo_fault(c)
    demo_eval(c)
    demo_governance(c)
    print("\n✅ 全部演示离线运行成功 —— 完整、可测试、可部署。")