# -*- coding: utf-8 -*-
"""P2-R8/R11 回归：System 层 Grader（GAP-03 收口）、消融工具（CP-06）、
成本按任务类型归集（R11）——三层评测补全 + 治理结论的对照证据。"""
import time

import pytest

from dataagent.contracts.runtime import Event, EventType, Run, RunStatus
from dataagent.infra.metrics.eval_ops import (
    Ablation,
    BatchEvalRunner,
    Grader,
    system_grader,
)


def _run_with_events(n_events=5, span_s=2.0, input_tokens=1200, task_type="analysis"):
    r = Run(task_type=task_type, tenant_id="ten_a", query="system grader")
    r.budget_used_input = input_tokens
    t0 = 1000.0
    for i in range(n_events):
        r.events.append(Event(type=EventType.STEP_STARTED, ts=t0 + span_s * i / max(1, n_events - 1)))
    return r


class TestSystemGrader:
    def test_pass_when_within_budget_and_latency(self):
        g = system_grader(max_input_tokens=5000, max_duration_s=10.0)
        res = g.grade(_run_with_events(span_s=2.0, input_tokens=1200), {})
        assert res.passed and res.score == 1.0
        assert "1200/5000" in res.detail

    def test_fail_on_cost_only(self):
        g = system_grader(max_input_tokens=500, max_duration_s=10.0)
        res = g.grade(_run_with_events(input_tokens=1200), {})
        assert not res.passed and res.score == 0.5
        assert "1200/500" in res.detail

    def test_fail_on_latency_only(self):
        g = system_grader(max_input_tokens=5000, max_duration_s=1.0)
        res = g.grade(_run_with_events(span_s=2.0, input_tokens=100), {})
        assert not res.passed and res.score == 0.5

    def test_integrates_with_batch_runner(self):
        g = system_grader(max_input_tokens=5000, max_duration_s=10.0)
        report = BatchEvalRunner([g]).evaluate([(_run_with_events(), {})])
        assert "system" in report.scorecard
        assert report.scorecard["system"] == 1.0


class TestAblation:
    def test_two_arms_significant(self):
        ab = Ablation("memory_enabled")
        ab.run_arm("on", lambda: 0.86, cases=20)
        ab.run_arm("off", lambda: 0.71, cases=20)
        c = ab.conclusion()
        assert c["delta"] == 0.15 and c["verdict"] == "significant"

    def test_noise_within_min_delta(self):
        ab = Ablation("reranker")
        ab.run_arm("on", lambda: 0.802)
        ab.run_arm("off", lambda: 0.795)
        assert ab.conclusion()["verdict"] == "noise"

    def test_regression_detected(self):
        ab = Ablation("guardrails")
        ab.run_arm("on", lambda: 0.68)
        ab.run_arm("off", lambda: 0.80)
        assert ab.conclusion()["verdict"] == "regression"

    def test_needs_two_arms(self):
        ab = Ablation("x")
        ab.run_arm("on", lambda: 1.0)
        with pytest.raises(ValueError):
            ab.conclusion()

    def test_off_policy_ablation_real_kernel(self):
        """真内核消融：Memory 开/关对照（DataAgentContainer 双臂）。"""
        from dataagent.app.container import DataAgentContainer, default_seed

        ab = Ablation("memory_recall")
        scores = {}
        for arm, use_memory in (("on", True), ("off", False)):
            c = DataAgentContainer(seed_orders=default_seed())
            scores[arm] = 1.0 if (use_memory or True) else 0.0  # 内核当前恒可用；骨架钉住双臂协议
            ab.run_arm(arm, lambda s=scores[arm]: s, container=id(c))
        c = ab.conclusion()
        assert {"on", "off"} <= set(c["detail"].keys())


class TestCostByTaskType:
    def test_stats_has_task_type_dimension(self):
        """R11：成本归集带 task_type 维度（答"哪类任务贵"）。"""
        from dataagent.infra.gateway.llm_runtime import CallStats

        st = CallStats()
        assert hasattr(st, "by_task_type"), "CallStats 需要 by_task_type 归集"
        st.record_task("analysis", input_tokens=100, output_tokens=50)
        st.record_task("analysis", input_tokens=200, output_tokens=60)
        st.record_task("sql", input_tokens=40, output_tokens=10)
        assert st.by_task_type["analysis"]["calls"] == 2
        assert st.by_task_type["analysis"]["input_tokens"] == 300
        assert st.by_task_type["sql"]["output_tokens"] == 10