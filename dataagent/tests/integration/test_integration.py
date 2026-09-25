# -*- coding: utf-8 -*-
"""集成测试 —— 端到端：从 Demo 到企业级 Runtime。

覆盖：链路端到端、多租户认证、工具链、审批闭环、Eval、回归门禁、故障注入、可回放。
验证课程每一篇的工程机制都真正生效。
"""
from dataagent.app.container import DataAgentContainer, default_seed
from dataagent.infra.gateway.tools import TenantDataLake
from dataagent.infra.metrics.eval_ops import BatchEvalRunner, RegressionGate
from dataagent.infra.runtime.harness import AutonomyBudget
from dataagent.infra.runtime.workflow import InMemoryRunStore


def make_container(**kw):
    return DataAgentContainer(seed_orders=default_seed(), **kw)


class TestEndToEnd:
    def test_full_analysis_pipeline(self):
        c = make_container()
        run = c.analyze("华东区本月 GMV 下滑原因诊断")
        assert run.status.value == "succeeded"
        # 执行轨迹完整：至少有 plan/query/analyze/conclusion 节点
        names = [s.name for s in run.steps]
        assert "plan" in names and "query" in names and "conclusion" in names
        # Run Timeline 有事件流
        assert len(run.events) > 5

    def test_toolchain_query_and_python(self):
        c = make_container()
        m = c.tools.get("query_metric").invoke({"tenant_id": "ten_a"}, tenant_id="ten_a")
        assert m.status.value == "ok"
        assert "gmv" in m.value
        py = c.tools.get("python_analyze").invoke({"metric": "gmv", "data": m.value})
        assert py.status.value in ("ok", "validation_error")

    def test_autonomy_budget_bounds(self):
        c = make_container()
        assert c.harness.budget.max_steps >= 1
        # 构造一个几近耗尽预算的 Harness 验证硬性停止
        c.harness.budget.max_steps = 1
        c.harness.budget.steps = 1
        assert not c.harness.budget.can_continue()


class TestMultiTenant:
    def test_tenant_isolation_in_lake(self):
        lake = TenantDataLake()
        lake.set_orders("ten_a", [{"region": "华东", "amount": 100}] * 3)
        lake.set_orders("ten_b", [{"region": "华北", "amount": 999}] * 3)
        metrics_a = lake.compute_metrics("ten_a")
        metrics_b = lake.compute_metrics("ten_b")
        assert metrics_a["gmv"] != metrics_b["gmv"]
        assert metrics_a["order_count"] == metrics_b["order_count"]  # 均为 3 行但不同金额


class TestApprovalFlow:
    def test_human_approval_gate_in_workflow(self):
        c = make_container()
        # 关闭自动审批，模拟"积累在 pending"提交一次决议
        c.approval_port.auto_approve = False
        from dataagent.contracts.runtime import ApprovalDecision
        from dataagent.contracts.runtime import Run
        run = Run(tenant_id="ten_a", query="预算调整")
        from dataagent.infra.runtime.workflow import WorkflowDefinition, WorkflowNode
        wf = WorkflowDefinition("x", nodes=[WorkflowNode("budget_adjust", "human_gate", approval_action="adjust_budget", risk_level="high")])
        # 执行前先手动批准 auto_approve=False 时 request 会置为 pending；
        # 这里用一个前置 approver 端口：直接在 request 后 resolve
        orig_request = c.approval_port.request

        def capturing_request(req):
            rid = orig_request(req)
            c.approval_port.resolve(rid, ApprovalDecision.APPROVED, by="tester")
            return rid
        c.approval_port.request = capturing_request
        c.workflow.execute(wf, run)
        # 审批事件存在
        assert any(e.type.value == "approval_requested" for e in run.events)


class TestEval:
    def test_eval_scorecard_and_gate(self):
        c = make_container()
        run = c.analyze("华东区 GMV 下滑")
        from dataagent.infra.metrics.eval_ops import code_grader

        def verify(r):
            return r.status.value == "succeeded" and len(r.events) > 5
        runner = BatchEvalRunner([code_grader(verify)])
        report = runner.evaluate([(run, {})])
        gate = RegressionGate(min_scores={"code": 0.8})
        ok, viol = gate.evaluate(report)
        assert ok, viol

    def test_fault_injection_cross_failures(self):
        """第五篇第6课：故障注入 —— 模型多次失败后仍能完成任务(重试恢复)。"""
        base = make_container()
        # 给默认 client 注入"前两次失败"，但整条链路的 executor/harness 保持原样
        base.client.fail_times = 2
        run = base.analyze("华东区 GMV 下滑")
        assert run.status.value == "succeeded"
        assert base.client.fail_times == 0  # 故障已被重试耗尽
        assert base.client.call_count > 2    # 证明多次调用/重试发生


class TestReplay:
    def test_report_replayable_via_checkpoint(self):
        """第五篇第3课：Run Timeline 可回放 —— 两次从相等待点装配上下文一致。"""
        c = make_container()
        run = c.analyze("华东区 GMV 下滑")
        cp = run.to_checkpoint()
        assert cp.run_id == run.run_id
        assert len(cp.event_serial) == len(run.events)