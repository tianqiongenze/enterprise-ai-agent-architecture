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
    ApprovalStatus,
    ApprovalTimeoutPolicy,
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
    idempotency_params: tuple[str, ...] = ()  # GAP-09: human_gate 声明哪些参数构成幂等键


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


def build_effect_key(action: str, params: dict[str, Any], declared: tuple[str, ...]) -> str:
    """按契约声明构造幂等键（GAP-09，与 Tool.build_effect_key 同哲学）。

    - 只取 ``declared`` 声明的副作用参数（排序拼接）；
    - params 中出现**未声明**的键 → 显式抛错：描述性参数（如 reason/结论措辞）
      混进幂等键会让"换个说法"变成一次新副作用（参照工程真实缺陷 #4）。
    """
    undeclared = sorted(set(params) - set(declared))
    if undeclared:
        raise ValueError(
            f"参数 {undeclared} 未在幂等契约声明，禁止进入幂等键（声明清单: {list(declared)}）"
        )
    parts = "&".join(f"{k}={params[k]}" for k in sorted(declared) if k in params)
    return f"{action}:{parts}"


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
    """内存审批端口：实现"请求→回执→决议"闭环 + 超时升级/过期（GAP-19a）。"""

    def __init__(self, auto_approve: bool = False, resolver=None,
                 *, timeout_policy: Optional[ApprovalTimeoutPolicy] = None,
                 clock: Optional[Callable[[], float]] = None,
                 sink: Optional[Any] = None) -> None:
        self._reqs: dict[str, ApprovalRequest] = {}
        self.auto_approve = auto_approve
        # 超时策略缺省 = 永不超时（M0 演示语义不变，向后兼容）
        self.timeout_policy = timeout_policy
        self._clock = clock or time.time
        self.sink = sink  # GAP-19a 运营通知端口（邮件/IM 适配点；None=仅事件流留痕）

    def request(self, req: ApprovalRequest) -> str:
        self._reqs[req.request_id] = req
        if self.auto_approve:
            self.resolve(req.request_id, ApprovalDecision.APPROVED, by="system:auto")
        return req.request_id

    def resolve(self, request_id: str, decision: ApprovalDecision, by: str) -> None:
        req = self._reqs[request_id]
        if req.status == ApprovalStatus.EXPIRED.value:
            raise ApprovalExpiredError(
                f"审批单 {request_id} 已过期 —— 过期后不得补批准（fail-closed）"
            )
        req.status = decision.value
        req.approvers = by

    def get(self, request_id: str) -> ApprovalRequest:
        return self._reqs[request_id]

    def pending_for(self, run_id: str, action: Optional[str] = None) -> list[ApprovalRequest]:
        return [
            r for r in self._reqs.values()
            if r.run_id == run_id and r.status == ApprovalStatus.PENDING.value
            and (action is None or r.action == action)
        ]

    def sweep_timeouts(self, *, run_id: Optional[str] = None,
                       now: Optional[float] = None) -> list[tuple[ApprovalRequest, str]]:
        """执行超时处置（判定归 policy，副作用归端口），返回 [(req, 处置状态)]。

        - expired：pending 超过 TTL → 置 EXPIRED（终态，不可补批准）；
        - escalate:<角色>：进入升级窗 → 沿链追加通知角色（escalation_history 留痕，
          链耗尽后等待过期，绝不静默放行）。
        """
        if self.timeout_policy is None:
            return []
        now = self._clock() if now is None else now
        actions: list[tuple[ApprovalRequest, str]] = []
        targets = [r for r in self._reqs.values()
                   if run_id is None or r.run_id == run_id]
        for req in targets:
            st = self.timeout_policy.timeout_state(req, now=now)
            if st == "waiting":
                continue
            if st == "expired":
                req.status = ApprovalStatus.EXPIRED.value
                req.note = req.note + f"超时过期 >{self.timeout_policy.pending_ttl_s:.0f}s; "
            elif st.startswith("escalate:"):
                role = st.split(":", 1)[1]
                req.escalation_history.append(role)
            actions.append((req, st))
            # 运营通知（GAP-19a）：升级/过期是"需要找到人"的事件，经 sink 外发
            if self.sink is not None:
                kind = ("approval_expired" if st == "expired"
                        else f"approval_escalated:{st.split(':', 1)[1]}")
                try:
                    self.sink.notify(kind, {"request_id": req.request_id, "run_id": req.run_id,
                                            "action": req.action,
                                            "to": ",".join(req.escalation_history)})
                except Exception as e:  # noqa: BLE001  通知故障不阻断巡检（fail-safe）
                    print(f"WARN notify 失败(已忽略): {e}")
        return actions


class ApprovalExpiredError(Exception):
    """向已过期审批单写入决议 —— GAP-19a 的 fail-closed 守门异常。"""


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
        return self.approval.get(request_id).status == ApprovalDecision.APPROVED.value

    def expired(self, request_id: str) -> bool:
        return self.approval.get(request_id).status == ApprovalStatus.EXPIRED.value

    # ---- GAP-19a：超时巡检经 gate 进入（工作流消费点） ----

    def supports_timeout_sweep(self) -> bool:
        return hasattr(self.approval, "sweep_timeouts")

    def sweep_timeouts(self, run_id: str) -> list[tuple[ApprovalRequest, str]]:
        if not self.supports_timeout_sweep():
            return []
        return self.approval.sweep_timeouts(run_id=run_id)


class DurableWorkflowExecutor:
    """可恢复的工作流执行器：逐步执行节点，每步结束保存 Checkpoint。"""

    def __init__(
        self,
        store: RunStore,
        approval: HumanApprovalGate,
        idem: IdempotencyStore,
        harness_runner: Optional[Callable[[Run, dict[str, Any]], Run]] = None,
        approval_mode: str = "auto",  # auto=演示自动通过 | manual=真实审批(中断-恢复)
        recorder: Optional[Any] = None,  # GAP-18: 事件流持久化接线（None=不落盘）
    ):
        self.store = store
        self.approval = approval
        self.idem = idem
        self.harness_runner = harness_runner
        self.approval_mode = approval_mode
        self.recorder = recorder
        self._recorded_len: dict[str, int] = {}

    def _persist_events(self, run: Run) -> None:
        """事件流增量落盘（GAP-18）。观测故障不得阻断业务链路：异常记警告后继续。"""
        if self.recorder is None:
            return
        try:
            self.recorder.record_run_events(run)
            self.recorder.record_checkpoint(run.to_checkpoint())  # 检查点快照（last-wins）
            self._recorded_len[run.run_id] = len(run.events)
        except Exception as e:  # noqa: BLE001
            print(f"WARN recorder 落盘失败(不阻断主链路): {e}")

    def _execute_gated_action(
        self, run: Run, step: Step, node: "WorkflowNode", action: str
    ) -> dict[str, Any]:
        """审批通过后的受控执行（GAP-09 接线）：幂等键先占 → 回执。

        - 幂等键按 ``node.idempotency_params`` 契约声明构造（未声明参数混入 → 显式报错）；
        - ``try_mark`` 原子先占：重复执行返回 idempotent_skip=True，副作用不再发生；
        - 回执与 effect_key 进入 step.output 与事件流（审计可查）。
        """
        params = dict(step.input or {})
        effect_key = build_effect_key(action, params, node.idempotency_params)
        first_time = self.idem.try_mark(effect_key)
        receipt = (
            build_approval_action(run, params) if first_time
            else {"action": "idempotent_skip", "params": params}
        )
        run.add_event(
            EventType.TOOL_CALL, step_id=step.step_id,
            data={"tool": action, "effect_key": effect_key, "idempotent_skip": not first_time},
        )
        return {"effect_key": effect_key, "idempotent_skip": not first_time, "receipt": receipt}

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
                        # 审批人已真实批准（恢复执行）：留痕 + 幂等受控执行
                        gate_out = self._execute_gated_action(run, step, node, action)
                        run.add_event(EventType.APPROVAL_RESOLVED, step_id=step.step_id,
                                      data={"approved": True, "by": decision.get("by", ""),
                                            "action": action, "effect_key": gate_out["effect_key"]})
                        step.output = {"approved": True, "by": decision.get("by", ""), **gate_out}
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
                        # GAP-19a：巡检本 Run 待审单 —— 升级提醒落事件（可运营），
                        # 过期单 fail-closed（超时≠放行：本步直接失败，终态 FAILED 可见）
                        for treq, tstate in self.approval.sweep_timeouts(run.run_id):
                            if tstate.startswith("escalate:"):
                                run.add_event(
                                    EventType.APPROVAL_ESCALATED, step_id=step.step_id,
                                    data={"request_id": treq.request_id,
                                          "escalated_to": ",".join(treq.escalation_history),
                                          "action": treq.action})
                            elif tstate == "expired":
                                if treq.request_id == req_id:
                                    run.add_event(
                                        EventType.APPROVAL_EXPIRED, step_id=step.step_id,
                                        data={"request_id": req_id, "action": action,
                                              "ttl_s": getattr(
                                                  getattr(self.approval.approval, "timeout_policy", None),
                                                  "pending_ttl_s", 0)})
                                    step.status = StepStatus.FAILED
                                    step.error = f"审批超时过期: {action} 无人决议（fail-closed）"
                                    run.status = RunStatus.FAILED
                                    self.store.save(run)
                                    self.store.save_checkpoint(run.to_checkpoint())
                                    self._persist_events(run)
                                    return run
                        run.status = RunStatus.WAITING_APPROVAL
                        self.store.save(run)
                        self.store.save_checkpoint(run.to_checkpoint())
                        if self.approval.is_approved(req_id):
                            # 审批已决（auto/立即通过）：恢复运行态再继续。
                            # 挂起态不是直达终态的旁路 —— 恢复必须显式回到 RUNNING，
                            # 这与 manual 模式下"带 pre_approved 恢复"的语义一致。
                            run.status = RunStatus.RUNNING
                            gate_out = self._execute_gated_action(run, step, node, action)
                            run.add_event(EventType.APPROVAL_RESOLVED, step_id=step.step_id,
                                          data={"approved": True, "effect_key": gate_out["effect_key"]})
                            step.output = {"approved": True, "request_id": req_id, **gate_out}
                        else:
                            # 审批未决（无决议）：流程不得带着挂起状态走向终态 ——
                            # 这正是状态机拒绝 waiting_approval→succeeded 的原因。
                            # 走 interrupt 语义（与 manual 模式一致），由上层决议后恢复。
                            self.store.save(run)
                            self.store.save_checkpoint(run.to_checkpoint())
                            raise ApprovalPendingError(action, dict(step.input or {}))
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
                # 终态保护：Run 已是终态（如子节点曾越权终结）时不得复活为 FAILED，
                # 否则会把状态机违规掩盖成业务失败 —— 直接上抛让缺陷可见。
                if not run.status.terminal:
                    run.status = RunStatus.FAILED
                    self.store.save(run)
                    self.store.save_checkpoint(run.to_checkpoint())
                    return run
                raise

            # 每步结束保存一次 Checkpoint → 支持中断恢复（GAP-18：同时落盘增量事件）
            self.store.save(run)
            self.store.save_checkpoint(run.to_checkpoint())
            self._persist_events(run)

        run.status = RunStatus.SUCCEEDED
        run.add_event(EventType.RUN_SUCCEEDED, data={"workflow": wf.name})
        self.store.save(run)
        self.store.save_checkpoint(run.to_checkpoint())
        self._persist_events(run)
        return run


def build_approval_action(run: Run, params: dict) -> dict:
    """作为 Workflow 的高风险副作用动作，返回执行回执。"""

    # 这里代表真实调用预算系统/工单系统（通过副作用幂等保护）
    return {"action": "side_effect_executed", "params": params}