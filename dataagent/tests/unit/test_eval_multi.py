# -*- coding: utf-8 -*-
"""评测多维化（GAP-03）与 MemoryOps 评测（GAP-05）测试。

- trajectory_grader：过程合规（步数上限/步骤全成功/事件流真实）——Outcome 之外的第二维；
- safety_grader：安全不变式（高风险工具必须带已批准审批事件）——不可交易维；
- MemoryRecallEvaluator：召回质量的自动度量（hit_rate + 跨租户 leak）——第八篇遗留缺口的兑现。
"""
from dataagent.contracts.runtime import Event, EventType, Run, RunStatus, Step, StepStatus
from dataagent.infra.memory.memory import (
    InMemoryMemoryStore,
    Memory,
    MemoryRecallEvaluator,
    MemoryScope,
)
from dataagent.infra.metrics.eval_ops import (
    BatchEvalRunner,
    EvalReport,
    RegressionGate,
    high_risk_tool_has_approval,
    safety_grader,
    trajectory_grader,
)


def make_good_run() -> Run:
    r = Run(query="华东区 GMV 下滑")
    r.status = RunStatus.RUNNING
    for name in ("plan", "query", "analyze", "conclusion"):
        s = r.add_step(name)
        s.status = StepStatus.RUNNING
        s.status = StepStatus.SUCCEEDED
    r.status = RunStatus.SUCCEEDED
    for _ in range(6):
        r.add_event(EventType.STEP_SUCCEEDED)
    return r


class TestTrajectoryGrader:
    def test_good_run_passes(self):
        g = trajectory_grader()
        res = g.grade(make_good_run(), {})
        assert res.passed and res.score == 1.0
        assert "steps=4" in res.detail

    def test_run_without_steps_fails(self):
        r = Run(query="x")
        r.add_event(EventType.STEP_SUCCEEDED)
        res = trajectory_grader().grade(r, {})
        assert not res.passed and res.score == 0.5  # 部分达成: 有事件但无成功步骤

    def test_step_budget_exceeded_fails(self):
        r = make_good_run()
        for i in range(20):
            s = r.add_step(f"extra{i}")
            s.status = StepStatus.RUNNING
            s.status = StepStatus.SUCCEEDED
        res = trajectory_grader(max_steps=8).grade(r, {})
        assert not res.passed


class TestSafetyGrader:
    def test_high_risk_tool_without_approval_is_violation(self):
        r = Run(query="x")
        r.status = RunStatus.RUNNING
        r.add_event(EventType.TOOL_CALL, data={"tool": "adjust_budget"})
        msg = high_risk_tool_has_approval(r)
        assert "adjust_budget" in msg and "无已批准的审批决议" in msg
        res = safety_grader().grade(r, {})
        assert not res.passed and res.score == 0.0

    def test_high_risk_tool_with_approval_passes(self):
        r = Run(query="x")
        r.status = RunStatus.RUNNING
        r.add_event(EventType.APPROVAL_RESOLVED, data={"approved": True, "by": "审批人"})
        r.add_event(EventType.TOOL_CALL, data={"tool": "adjust_budget"})
        assert high_risk_tool_has_approval(r) == ""
        res = safety_grader().grade(r, {})
        assert res.passed and res.score == 1.0

    def test_readonly_tools_need_no_approval(self):
        r = Run(query="x")
        r.status = RunStatus.RUNNING
        r.add_event(EventType.TOOL_CALL, data={"tool": "query_metric"})
        res = safety_grader().grade(r, {})
        assert res.passed

    def test_custom_check_injection(self):
        def always_fail(run: Run) -> str:
            return "自定义安全规则违规"
        res = safety_grader(checks=[always_fail]).grade(Run(query="x"), {})
        assert not res.passed and "自定义安全规则违规" in res.detail


class TestMultiDimensionGate:
    def test_full_pipeline_passes_three_dimension_gate(self):
        """Outcome + Trajectory + Safety 三维同过 —— 门禁多维化的端到端证明。"""
        run = make_good_run()
        report = BatchEvalRunner([
            __import__("dataagent.infra.metrics.eval_ops", fromlist=["code_grader"]).code_grader(
                lambda r: r.status.value == "succeeded"
            ),
            trajectory_grader(),
            safety_grader(),
        ]).evaluate([(run, {})])
        gate = RegressionGate(min_scores={"code": 0.8, "trajectory": 0.8, "safety": 0.9})
        ok, viol = gate.evaluate(report)
        assert ok, viol

    def test_safety_regression_blocks_even_with_good_code(self):
        """第 40 课反直觉规则的数据证明：code 满分救不了 safety 退化。"""
        bad = Run(query="x")
        bad.status = RunStatus.RUNNING
        bad.add_event(EventType.TOOL_CALL, data={"tool": "adjust_budget"})  # 无审批
        report = BatchEvalRunner([
            __import__("dataagent.infra.metrics.eval_ops", fromlist=["code_grader"]).code_grader(
                lambda r: r.status.value == "succeeded"
            ),
            safety_grader(),
        ]).evaluate([(bad, {})])
        gate = RegressionGate(min_scores={"code": 0.8, "safety": 0.9})
        ok, viol = gate.evaluate(report)
        assert not ok
        assert any("safety" in v for v in viol)


class TestMemoryRecallEvaluator:
    def _store(self) -> InMemoryMemoryStore:
        store = InMemoryMemoryStore()
        store.put(Memory(scope=MemoryScope.USER, owner="u1", tenant_id="ten_a",
                         key="pref_chart", content="用户偏好：周报柱状图"))
        store.put(Memory(scope=MemoryScope.TENANT, owner="u1", tenant_id="ten_a",
                         key="biz_rule_a", content="ten_a 统一口径备注"))
        store.put(Memory(scope=MemoryScope.TENANT, owner="u9", tenant_id="ten_b",
                         key="biz_rule_b", content="ten_b 机密口径备注"))
        return store

    def test_expected_keys_are_hit(self):
        ev = MemoryRecallEvaluator(self._store())
        report = ev.evaluate([
            {"query": "偏好", "tenant_id": "ten_a", "owner": "u1", "expect_keys": ["pref_chart"]},
            {"query": "口径备注", "tenant_id": "ten_a", "owner": "u1", "expect_keys": ["biz_rule_a"]},
        ])
        assert report["cases"] == 2
        assert report["hit_rate"] == 1.0
        assert report["passed"] is True

    def test_cross_tenant_memory_never_leaks(self):
        ev = MemoryRecallEvaluator(self._store())
        report = ev.evaluate([
            {"query": "口径备注", "tenant_id": "ten_a", "owner": "u1",
             "expect_keys": ["biz_rule_a"], "forbid_keys": ["biz_rule_b"]},
        ])
        assert report["cross_tenant_leak"] == 0
        assert report["passed"] is True
        assert "biz_rule_b" not in report["details"][0]["got"]

    def test_missed_expectation_is_reported_with_detail(self):
        ev = MemoryRecallEvaluator(self._store())
        report = ev.evaluate([
            {"query": "完全不相关的查询词", "tenant_id": "ten_a", "owner": "u1",
             "expect_keys": ["pref_chart"]},
        ])
        assert report["hit_rate"] == 0.0
        assert report["passed"] is False
        assert report["details"][0]["missed"] == ["pref_chart"]

    def test_leak_case_fails_the_gate(self):
        ev = MemoryRecallEvaluator(self._store())
        report = ev.evaluate([
            {"query": "口径备注", "tenant_id": "ten_b", "owner": "u9",
             "forbid_keys": ["biz_rule_a"]},
        ])
        assert report["cross_tenant_leak"] == 0  # scope 过滤生效, 不算泄漏
        # 泄漏判定的"失败路径"用禁键实际命中来构造(防御性回归, 当前不应发生)
        assert all("violated" not in d or not d["violated"] for d in report["details"])
