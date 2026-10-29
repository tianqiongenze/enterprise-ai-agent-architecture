# -*- coding: utf-8 -*-
"""统一执行模型 · 数据化状态机测试（第五篇第3课）。

TDD 纪律：状态机严格化是行为变更 —— 非法迁移必须抛 ``InvalidStateTransition``，
终态不可复活，恢复（restore）属于物化不走迁移校验。
本文件同时钉住 ``VerifierFailedError`` 的节点级失败语义（完成判据只挂可观测事实上）。
"""
import pytest

from dataagent.contracts.runtime import (
    RUN_STATE_MACHINE,
    STEP_STATE_MACHINE,
    Event,
    EventType,
    InvalidStateTransition,
    Run,
    RunStatus,
    Step,
    StepStatus,
)


class TestRunStateMachine:
    def test_pending_to_running_is_legal(self):
        r = Run(query="x")
        r.status = RunStatus.RUNNING  # pending -> running ✓
        assert r.status is RunStatus.RUNNING

    def test_pending_to_succeeded_is_rejected(self):
        r = Run(query="x")
        with pytest.raises(InvalidStateTransition):
            r.status = RunStatus.SUCCEEDED  # pending -> succeeded ✗ 跳过运行期

    def test_terminal_cannot_be_revived(self):
        r = Run(query="x")
        r.status = RunStatus.RUNNING
        r.status = RunStatus.SUCCEEDED
        with pytest.raises(InvalidStateTransition):
            r.status = RunStatus.RUNNING  # 终态复活 ✗
        with pytest.raises(InvalidStateTransition):
            r.status = RunStatus.FAILED  # succeeded -> failed ✗

    def test_same_value_assignment_is_noop(self):
        """幂等重入：同值赋值放行（workflow/harness 重入同一状态是正常路径）。"""
        r = Run(query="x")
        r.status = RunStatus.RUNNING
        r.status = RunStatus.RUNNING  # no-op ✓
        assert r.status is RunStatus.RUNNING

    def test_waiting_approval_resume_requires_running(self):
        """挂起态不是直达终态的旁路：恢复必须显式回到 RUNNING。"""
        r = Run(query="x")
        r.status = RunStatus.RUNNING
        r.status = RunStatus.WAITING_APPROVAL
        with pytest.raises(InvalidStateTransition):
            r.status = RunStatus.SUCCEEDED  # waiting_approval -> succeeded ✗
        r.status = RunStatus.RUNNING  # ✓ 显式恢复
        r.status = RunStatus.SUCCEEDED  # running -> succeeded ✓

    def test_restore_bypasses_transition_check(self):
        """恢复是物化不是迁移：从 Checkpoint 可重建到任意已持久化状态。"""
        r = Run(query="x")
        r.status = RunStatus.RUNNING
        cp = r.to_checkpoint()
        r2 = Run()
        r2.restore(cp)  # 物化，不走迁移校验
        assert r2.status == RunStatus.RUNNING

    def test_transition_table_is_reviewable(self):
        """状态机是数据：迁移表可打印、可评审。"""
        table = RUN_STATE_MACHINE.to_table()
        assert "StateMachine<Run>" in table
        assert "pending" in table and "succeeded" in table

    def test_terminal_states_have_no_outgoing_edges(self):
        for t in RUN_STATE_MACHINE.terminal:
            assert not RUN_STATE_MACHINE.can_transition(t, "running")


class TestStepStateMachine:
    def test_step_lifecycle(self):
        s = Step(step_id="stp_0001", name="plan")
        s.status = StepStatus.RUNNING
        s.status = StepStatus.SUCCEEDED
        assert s.status is StepStatus.SUCCEEDED

    def test_step_cannot_skip_running_to_succeeded(self):
        """pending -> succeeded 非法（没跑过不能成功）；pending -> failed 合法（依赖失败）。"""
        s = Step(step_id="stp_0002", name="query")
        with pytest.raises(InvalidStateTransition):
            s.status = StepStatus.SUCCEEDED  # pending -> succeeded ✗
        s.status = StepStatus.FAILED  # pending -> failed ✓（依赖失败语义）

    def test_step_waiting_approval_is_recoverable(self):
        s = Step(step_id="stp_0003", name="human_gate")
        s.status = StepStatus.RUNNING
        s.status = StepStatus.WAITING_APPROVAL
        s.status = StepStatus.RUNNING  # 恢复 ✓


class TestVerifierSemantics:
    def test_verifier_failure_fails_run_via_workflow(self):
        """完成判据只挂可观测事实上：Verifier 失败 -> 节点失败 -> Run FAILED。"""
        from dataagent.infra.runtime.harness import Harness, Verifier, VerifierFailedError
        from dataagent.infra.runtime.workflow import (
            DurableWorkflowExecutor,
            HumanApprovalGate,
            IdempotencyStore,
            InMemoryApprovalPort,
            InMemoryRunStore,
            WorkflowDefinition,
            WorkflowNode,
        )

        class _StubRunner:
            """最小 Harness 替身：验证失败即抛 VerifierFailedError。"""

            def __init__(self):
                self.budget = type("B", (), {"max_steps": 1, "steps": 0})()

            def run(self, run, tenant_id):
                raise VerifierFailedError("结论缺少证据引用")

        wf = WorkflowDefinition("x", nodes=[WorkflowNode("h", "harness")])
        ex = DurableWorkflowExecutor(
            store=InMemoryRunStore(),
            approval=HumanApprovalGate(InMemoryApprovalPort(auto_approve=True)),
            idem=IdempotencyStore(),
            harness_runner=_StubRunner().run,
        )
        run = ex.execute(wf, Run(query="x"))
        assert run.status is RunStatus.FAILED
        assert any(
            e.type is EventType.STEP_FAILED and "verifier" in str(e.data.get("error", ""))
            for e in run.events
        )
