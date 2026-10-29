# -*- coding: utf-8 -*-
"""评测集 v2：三类失败终态反例（预算耗尽 / 审批拒绝 / Verifier 失败）。

正例证明"能做对"，反例证明"该失败时**以正确的终态失败**"——
三类终态各有 case 且终态可机器判定（第 40 课 RegressionGate 的反例面）。
"""
import pytest

from pathlib import Path

from dataagent.app.container import DataAgentContainer, default_seed
from dataagent.contracts.runtime import Run, RunStatus
from dataagent.infra.metrics.eval_ops import Dataset
from dataagent.infra.runtime.workflow import (
    DurableWorkflowExecutor,
    HumanApprovalGate,
    IdempotencyStore,
    InMemoryApprovalPort,
    InMemoryRunStore,
    WorkflowDefinition,
    WorkflowNode,
)


class TestFailureTerminals:
    """三类失败终态：每一类都钉住"终态语义正确"而非"没崩"。"""

    def test_budget_exhaustion_fails_run(self):
        """终态1 预算耗尽：max_steps=0 → 后续步不执行 → FAILED（不是带病成功）。"""
        c = DataAgentContainer(seed_orders=default_seed())
        c.harness.budget.max_steps = 0  # 限额模板：0 = 全部自主步禁用
        run = c.analyze("华东区 GMV 下滑")
        assert run.status is RunStatus.FAILED
        skipped = [s.name for s in run.steps if s.status.value == "pending"]
        assert "query" in skipped  # 自主步确实被预算拦下

    def test_approval_rejection_cancels_run(self):
        """终态2 审批拒绝：人说不 → CANCELED（终态，不是 FAILED 也不是继续）。"""
        ex = DurableWorkflowExecutor(
            store=InMemoryRunStore(),
            approval=HumanApprovalGate(InMemoryApprovalPort(auto_approve=True)),
            idem=IdempotencyStore(), harness_runner=None)
        wf = WorkflowDefinition("x", nodes=[WorkflowNode("g", "human_gate",
                                                         approval_action="adjust_budget")])
        run = ex.execute(wf, Run(query="x"),
                         pre_approved={"adjust_budget": {"decision": "rejected", "by": "审批人"}})
        assert run.status is RunStatus.CANCELED

    def test_verifier_failure_fails_run(self):
        """终态3 Verifier 失败：完成判据不满足 → FAILED（fail-closed）。"""
        from dataagent.infra.runtime.harness import VerifierFailedError
        ex = DurableWorkflowExecutor(
            store=InMemoryRunStore(),
            approval=HumanApprovalGate(InMemoryApprovalPort(auto_approve=True)),
            idem=IdempotencyStore(),
            harness_runner=self._failing_harness)
        wf = WorkflowDefinition("x", nodes=[WorkflowNode("h", "harness")])
        run = ex.execute(wf, Run(query="x"))
        assert run.status is RunStatus.FAILED
        assert any("verifier" in str(e.data.get("error", "")) for e in run.events
                   if e.type.value == "step_failed")

    @staticmethod
    def _failing_harness(run, ctx):
        from dataagent.infra.runtime.harness import VerifierFailedError
        raise VerifierFailedError("结论缺少证据链（构造）")


class TestDatasetV2TerminalCoverage:
    def test_dataset_v2_has_three_negative_terminals(self):
        ds = Dataset.load(Path(__file__).resolve().parents[2] / "evals" / "dataset_v2.jsonl")
        negs = {c["expect"]["terminal"] for c in ds.cases if c["meta"].get("kind") == "negative"}
        assert {"failed_budget", "canceled_rejected", "failed_verifier"} <= negs
