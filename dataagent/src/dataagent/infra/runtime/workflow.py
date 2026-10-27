# -*- coding: utf-8 -*-
"""Durable Workflow (第五篇第4课)：把自主分析收口到可中断、可审批、可恢复的流程。

Workflow Shell —— 为什么开放分析必须放进 Workflow？因为真实业务需要：
- Checkpoint 与 Resume：长任务中断后从检查点恢复，而非重跑
- Human Approval：高风险副作用在执行前必须人工授权
- 副作用幂等：可重试执行不会导致真实业务被重复写入
- Run Timeline：可解释每一步在做什么，供运维与审计

Workflow 由节点 (Step) 构成的有向图驱动。节点可以是：
  - 确定性节点（纯代码）
  - Verifier 节点
  - Human Gate（等待人工审批）
  - Autonomous Harness 子流程（复用第五篇第2课）
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ...contracts.runtime import (
    ApprovalPendingError,
    Action,
    ApprovalDecision,
    ApprovalPort,
    ApprovalRequest,
    Checkpoint,
    EventType,
    Run,
    RunStatus,
    RunStore,
    Step,
    StepStatus,
)

WORKFLOW_EXTENSION = "workflow"


class WorkflowError(Exception):
    pass


@dataclass
class WorkflowNode:
    name: str
    kind: str  # task / verifier / human_gate / harness
    fn: Optional[Callable[[Run, dict[str, Any]], dict[str, Any]]] = None
    approval_action: Optional[str] = None  # kind=human_gate 时对应的副作用动作
    risk_level: str = "low"
    retries: int = 0


class WorkflowDefinition:
    """节点序列（本课程用线性 DAG；真实企业可扩展到任意图）。"""

    def __init__(self, name: str, nodes: list[WorkflowNode]):
        self.name = name
        self.nodes = nodes


class IdempotencyStore:
    """副作用幂等：以幂等键记录已执行的动作，防止重复写入真实业务。"""

    def __init__(self) -> None:
        self._executed: set[str] = set()

    def try_mark(self, key: str) -> bool:
        """若 key 已执行返回 False，否则标记并返回 True（只有第一次能执行）。"""
        if key in self._executed:
            return False
        self._executed.add(key)
        return True

    def has(self, key: str) -> bool:
        return key in self._executed


class InMemoryRunStore(RunStore):
    """内存 Run/Checkpoint 持久化端口实现（生产可替换为 Postgres/Redis）。"""

    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}
        self._cps: dict[str, Checkpoint] = {}

    def save(self, run: Run) -> None:
        self._runs[run.run_id] = run

    def load(self, run_id: str) -> Run:
        r = self._runs.get(run_id)
        if r is None:
            raise KeyError(run_id)
        return r

    def save_checkpoint(self, cp: Checkpoint) -> None:
        self._cps[cp.run_id] = cp

    def load_checkpoint(self, run_id: str) -> Optional[Checkpoint]:
        return self._cps.get(run_id)


class InMemoryApprovalPort(ApprovalPort):
    """内存审批端口：实现"请求→回执→决议"闭环。"""

    def __init__(self, auto_approve: bool = False, resolver=None) -> None:
        self._reqs: dict[str, ApprovalRequest] = {}
        self.auto_approve = auto_approve

    def request(self, req: ApprovalRequest) -> str:
        redirect = {}
        self._reqs[req.request_id] = req
        if self.auto_approve:
            self.resolve(req.request_id, ApprovalDecision.APPROVED, by="system:auto")
        return req.request_id

    def resolve(self, request_id: str, decision: ApprovalDecision, by: str) -> None:
        req = self._reqs[request_id]
        req.status = decision.value
        if decision == ApprovalDecision.REJECTED:
            pass

    def get(self, request_id: str) -> ApprovalRequest:
        return self._reqs[request_id]


class HumanApprovalGate:
    """Human Approval：让人参与关键决策 —— 解决高风险操作无法治理。"""

    def __init__(self, approval: ApprovalPort):
        self.approval = approval

    def request(
        self, run_id: str, action: str, params: dict[str, Any], risk_level: str = "high"
    ) -> str:
        req = ApprovalRequest(
            request_id=f"apr_{int(time.time()*1000)}",
            run_id=run_id,
            action=action,
            params=params,
            risk_level=risk_level,
        )
        return self.approval.request(req)

    def is_approved(self, request_id: str) -> bool:
        return self.approval.get(request_id).status == "approved"


class DurableWorkflowExecutor:
    """可恢复的工作流执行器：逐步执行节点，每步结束保存 Checkpoint。"""

    def __init__(
        self,
        store: RunStore,
        approval: HumanApprovalGate,
        idem: IdempotencyStore,
        harness_runner: Optional[Callable[[Run, dict[str, Any]], Run]] = None,
        approval_mode: str = "auto",  # auto=演示自动通过 | manual=真实审批(中断-恢复)
    ):
        self.store = store
        self.approval = approval
        self.idem = idem
        self.harness_runner = harness_runner
        self.approval_mode = approval_mode

    def execute(self, wf: WorkflowDefinition, run: Run, pre_approved: Optional[dict[str, Any]] = None) -> Run:
        """执行工作流；若 Run 已有 Checkpoint 则从中恢复（Resume）。

        pre_approved: 恢复执行时由上层注入的审批决议（{"action": {"decision": "approved", "by": ...}}），
        实现 HITL 的 interrupt/resume —— 人工审批真实发生后工作流才继续。"""
        cp = self.store.load_checkpoint(run.run_id)
        start_idx = 0
        executed = set()
        if cp is not None:
            # Resume：跳过已完成节点
            for idx, (sid, status) in enumerate(cp.step_serial):
                if status == StepStatus.SUCCEEDED.value:
                    executed.add(sid)
                    start_idx = idx + 1
            run.restore(cp)

        run.status = RunStatus.RUNNING
        run.add_event(EventType.RUN_STARTED, data={"workflow": wf.name})

        for node in wf.nodes:
            if node.name in executed:
                continue
            step = run.add_step(node.name)
            step.status = StepStatus.RUNNING
            step.started_at = time.time()
            run.add_event(EventType.STEP_STARTED, step_id=step.step_id, data={"node": node.name, "kind": node.kind})

            try:
                if node.kind == "harness" and self.harness_runner is not None:
                    run = self.harness_runner(run, {"node": node.name})
                elif node.kind == "human_gate":
                    action = node.approval_action or node.name
                    decision = (pre_approved or {}).get(action)
                    if decision and decision.get("decision") == "approved":
                        # 审批人已真实批准（恢复执行）：留痕后放行
                        run.add_event(EventType.APPROVAL_RESOLVED, step_id=step.step_id,
                                      data={"approved": True, "by": decision.get("by", ""),
                                            "action": action})
                        step.output = {"approved": True, "by": decision.get("by", "")}
                    elif decision and decision.get("decision") == "rejected":
                        run.add_event(EventType.APPROVAL_RESOLVED, step_id=step.step_id,
                                      data={"approved": False, "by": decision.get("by", "")})
                        run.status = RunStatus.CANCELED
                        step.status = StepStatus.SUCCEEDED
                        step.output = {"approved": False, "canceled": True}
                        self.store.save(run)
                        self.store.save_checkpoint(run.to_checkpoint())
                        return run
                    elif self.approval_mode == "manual":
                        # 真实审批模式：在此中断（interrupt），由上层创建审批单并持久化；
                        # 审批通过后带 pre_approved 恢复（resume）。
                        run.status = RunStatus.WAITING_APPROVAL
                        run.add_event(EventType.APPROVAL_REQUESTED, step_id=step.step_id,
                                      data={"action": action, "params": dict(step.input or {})})
                        self.store.save(run)
                        self.store.save_checkpoint(run.to_checkpoint())
                        raise ApprovalPendingError(action, dict(step.input or {}))
                    else:
                        req_id = self.approval.request(run.run_id, action, {})
                        run.add_event(EventType.APPROVAL_REQUESTED, step_id=step.step_id, data={"request_id": req_id})
                        run.status = RunStatus.WAITING_APPROVAL
                        self.store.save(run)
                        self.store.save_checkpoint(run.to_checkpoint())
                        if self.approval.is_approved(req_id):
                            run.add_event(EventType.APPROVAL_RESOLVED, step_id=step.step_id, data={"approved": True})
                            step.output = {"approved": True, "request_id": req_id}
                        else:
                            step.output = {"approved": False, "request_id": req_id}
                else:  # task / verifier
                    if node.fn is not None:
                        step.output = node.fn(run, step.input) or {}
                step.status = StepStatus.SUCCEEDED
                step.finished_at = time.time()
            except ApprovalPendingError:
                # 审批中断不是故障：向上传播以创建审批单（HITL interrupt）
                step.status = StepStatus.WAITING_APPROVAL
                step.finished_at = time.time()
                self.store.save(run)
                self.store.save_checkpoint(run.to_checkpoint())
                raise
            except Exception as e:  # noqa: BLE001
                step.status = StepStatus.FAILED
                step.error = str(e)
                step.finished_at = time.time()
                run.add_event(EventType.STEP_FAILED, step_id=step.step_id, data={"error": str(e)})
                run.status = RunStatus.FAILED
                self.store.save(run)
                self.store.save_checkpoint(run.to_checkpoint())
                return run

            # 每步结束保存一次 Checkpoint → 支持中断恢复
            self.store.save(run)
            self.store.save_checkpoint(run.to_checkpoint())

        run.status = RunStatus.SUCCEEDED
        run.add_event(EventType.RUN_SUCCEEDED, data={"workflow": wf.name})
        self.store.save(run)
        self.store.save_checkpoint(run.to_checkpoint())
        return run


def build_approval_action(run: Run, params: dict) -> dict:
    """作为 Workflow 的高风险副作用动作，返回执行回执。"""

    # 这里代表真实调用预算系统/工单系统（通过副作用幂等保护）
    return {"action": "side_effect_executed", "params": params}