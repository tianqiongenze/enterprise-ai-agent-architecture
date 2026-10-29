# -*- coding: utf-8 -*-
"""统一执行模型 (Unified Runtime Domain)。

Alignment: 第五篇《Agent Harness 与 Agent Runtime 工程架构篇》
- Run / Step / Attempt / Event / Checkpoint / Run State Machine
- Task, Scheduler, Queue, Worker 基础设施接口
- Human Approval, Side-effect 幂等, 多租户资源

状态机纪律（对齐第五篇第3课 + 参照工程 dataagent-course 的不变式设计）：
- **状态机是数据不是代码**：RUN_STATE_MACHINE / STEP_STATE_MACHINE 是模块级常量，
  可打印（``to_table()``）、可评审、可断言；
- **非法迁移直接抛 ``InvalidStateTransition``**，而不是静默纠正——
  ``run.status = ...`` 的赋值点天然经过 ``__setattr__`` 校验，
  让"忘记走状态机"在第一次运行时就暴露，而不是在审计时才被发现；
- **恢复（restore）是物化不是迁移**：从 Checkpoint 重建 Run 允许落到任何
  已持久化状态，绕过迁移校验（经 ``object.__setattr__``）。
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Generic, Optional, Protocol, TypeVar

T = TypeVar("T")


class InvalidStateTransition(Exception):
    """非法状态迁移 —— 状态机纪律的结构化保证。

    对齐第五篇：任何状态变更必须经由状态机；非法迁移是程序缺陷而非业务分支，
    因此必须抛异常（fail-fast），让缺陷在第一次运行时暴露。
    """

    def __init__(self, machine: str, src: str, dst: str):
        super().__init__(
            f"[{machine}] 非法状态迁移: {src} -> {dst}。"
            f"合法迁移见 {machine}_STATE_MACHINE.to_table()"
        )
        self.machine = machine
        self.src = src
        self.dst = dst


class StateMachine:
    """数据化状态机：迁移表 + 终态集，可评审、可打印、可断言。

    为什么用数据而不是 if/else：迁移表本身就是架构评审对象——
    "哪些迁移合法"应该一眼可查，而不是散落在代码各处的赋值语句里。
    """

    def __init__(
        self,
        name: str,
        transitions: dict[str, set[str] | frozenset[str]],
        terminal: set[str] | frozenset[str],
    ):
        self.name = name
        self._transitions: dict[str, frozenset[str]] = {
            k: frozenset(v) for k, v in transitions.items()
        }
        self.terminal = frozenset(terminal)
        # 终态不允许作为迁移起点（终态即结束；显式恢复须走业务层 requeue 语义）
        for t in self.terminal:
            if t in self._transitions:
                raise ValueError(f"[{name}] 终态 {t} 不应出现在迁移表中作为起点")

    def can_transition(self, src: str, dst: str) -> bool:
        """同值赋值视为 no-op 放行（幂等重入）；否则查迁移表；终态无出边。"""
        if src == dst:
            return True
        if src in self.terminal:
            return False
        return dst in self._transitions.get(src, frozenset())

    def assert_transition(self, src: str, dst: str) -> None:
        if not self.can_transition(src, dst):
            raise InvalidStateTransition(self.name, src, dst)

    def to_table(self) -> str:
        """渲染迁移表（评审/教学用）。"""
        lines = [f"StateMachine<{self.name}> terminal={sorted(self.terminal)}"]
        for src in sorted(self._transitions):
            lines.append(f"  {src} -> {sorted(self._transitions[src])}")
        return "\n".join(lines)


RUN_STATE_MACHINE = StateMachine(
    name="Run",
    transitions={
        "pending": {"running", "canceled"},
        "running": {"paused", "waiting_approval", "succeeded", "failed", "canceled"},
        "paused": {"running", "failed", "canceled"},
        "waiting_approval": {"running", "failed", "canceled"},
    },
    terminal={"succeeded", "failed", "canceled"},
)

STEP_STATE_MACHINE = StateMachine(
    name="Step",
    transitions={
        "pending": {"running", "skipped", "failed"},
        "running": {"waiting_approval", "succeeded", "failed", "skipped"},
        "waiting_approval": {"running", "succeeded", "failed", "skipped"},
    },
    terminal={"succeeded", "failed", "skipped"},
)


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"  # 等待人工审批 / 资源
    WAITING_APPROVAL = "waiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"

    @property
    def terminal(self) -> bool:
        return self in (RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELED)


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    WAITING_APPROVAL = "waiting_approval"


class EventType(str, Enum):
    RUN_STARTED = "run_started"
    STEP_STARTED = "step_started"
    STEP_SUCCEEDED = "step_succeeded"
    STEP_FAILED = "step_failed"
    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    CONTEXT_ASSEMBLED = "context_assembled"
    MEMORY_WRITE = "memory_write"
    EVAL = "eval"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_RESOLVED = "approval_resolved"
    APPROVAL_ESCALATED = "approval_escalated"  # GAP-19a: 到点升级提醒留痕
    APPROVAL_EXPIRED = "approval_expired"      # GAP-19a: 超时失效（fail-closed，非默认放行）
    CHECKPOINT = "checkpoint"
    RUN_SUCCEEDED = "run_succeeded"
    RUN_FAILED = "run_failed"


@dataclass(frozen=True)
class Event:
    event_id: str = field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:10]}")
    run_id: str = ""
    step_id: str = ""
    type: EventType = EventType.RUN_STARTED
    ts: float = field(default_factory=time.time)
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Step:
    step_id: str
    name: str
    status: StepStatus = StepStatus.PENDING
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    attempts: int = 0
    error: Optional[str] = None
    events: list[Event] = field(default_factory=list)
    started_at: float = 0.0
    finished_at: float = 0.0

    def __setattr__(self, name: str, value: Any) -> None:
        # 状态机纪律：status 赋值必须经过 STEP_STATE_MACHINE（初始赋值除外）。
        if name == "status":
            old = self.__dict__.get("status")
            if old is not None:
                STEP_STATE_MACHINE.assert_transition(
                    old.value, value.value if isinstance(value, StepStatus) else str(value)
                )
        object.__setattr__(self, name, value)


@dataclass
class Run:
    """一个业务任务的完整执行记录 —— 统一 Runtime 语言。

    状态纪律：``run.status = ...`` 的赋值会经 RUN_STATE_MACHINE 校验，
    非法迁移（如 pending -> succeeded、终态复活）直接抛 ``InvalidStateTransition``；
    从 Checkpoint 重建（``restore``）属于物化，不走迁移校验。
    """

    run_id: str = field(default_factory=lambda: f"run_{uuid.uuid4().hex[:10]}")
    tenant_id: str = "default"
    user_id: str = "default"
    task_type: str = "analysis"
    query: str = ""
    status: RunStatus = RunStatus.PENDING
    steps: list[Step] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    checkpoint: Optional["Checkpoint"] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    budget_used_input: int = 0
    budget_used_output: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __setattr__(self, name: str, value: Any) -> None:
        # 状态机纪律：status 赋值必须经过 RUN_STATE_MACHINE（初始赋值除外）。
        if name == "status":
            old = self.__dict__.get("status")
            if old is not None:
                RUN_STATE_MACHINE.assert_transition(
                    old.value, value.value if isinstance(value, RunStatus) else str(value)
                )
        object.__setattr__(self, name, value)

    def add_event(
        self,
        type_: EventType,
        step_id: str = "",
        data: Optional[dict[str, Any]] = None,
        **extra: Any,
    ) -> Event:
        """追加事件。

        载荷语义：``data={...}`` 或零散 kwargs 都直接作为事件载荷（扁平结构），
        而不是把整个 dict 套进 ``{"data": {...}}`` —— 后者会让所有消费方
        都得写 ``e.data["data"]["x"]``，属于接口陷阱。
        """
        payload: dict[str, Any] = dict(data or {})
        payload.update(extra)
        evt = Event(
            run_id=self.run_id, step_id=step_id, type=type_, data=payload
        )
        self.events.append(evt)
        self.updated_at = time.time()
        return evt

    def add_step(self, name: str) -> Step:
        step = Step(step_id=f"stp_{len(self.steps) + 1:04d}", name=name)
        self.steps.append(step)
        return step

    def to_checkpoint(self) -> "Checkpoint":
        """将可恢复的最小状态固化为 Checkpoint。"""
        return Checkpoint(
            run_id=self.run_id,
            status=self.status,
            step_serial=[(s.step_id, s.status.value) for s in self.steps],
            event_serial=[
                (e.event_id, e.type.value, e.ts, e.data) for e in self.events
            ],
            budget=(self.budget_used_input, self.budget_used_output),
        )

    def restore(self, cp: "Checkpoint") -> None:
        """从 Checkpoint 物化恢复 —— 属于重建而非状态迁移，绕过迁移校验。"""
        object.__setattr__(self, "status", cp.status)
        self.events = [
            Event(event_id=eid, type=EventType(etype), ts=ts, data=data)
            for eid, etype, ts, data in cp.event_serial
        ]
        self.budget_used_input, self.budget_used_output = cp.budget


@dataclass
class Checkpoint:
    run_id: str
    status: RunStatus
    step_serial: list[tuple[str, str]]
    event_serial: list[tuple[str, str, float, dict[str, Any]]]
    budget: tuple[int, int]
    created_at: float = field(default_factory=time.time)


class RunStore(Protocol):
    """Run/Checkpoint 的持久化端口 (Port)。"""

    def save(self, run: Run) -> None: ...
    def load(self, run_id: str) -> Run: ...
    def save_checkpoint(self, cp: Checkpoint) -> None: ...
    def load_checkpoint(self, run_id: str) -> Optional[Checkpoint]: ...


class NotificationSink(Protocol):
    """运营通知端口（GAP-19a 生产化）：审批升级/过期等"需要找到人"的事件经此外发。

    适配方向：邮件/IM/Webhook 各实现一个 sink；默认 LogSink 只打印不外发（演示诚实）。
    """

    def notify(self, kind: str, payload: dict[str, Any]) -> None: ...


class ApprovalDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalStatus(str, Enum):
    """审批单生命周期（GAP-19a）：pending → 批准/拒绝/超时过期。

    过期是第四种终态：**超时 ≠ 放行** —— 没有人拍板资金动作，默认只能失效，
    把"拖过审批窗"变成可被绕过审批的攻击面是审批设计的反例。
    """

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"

    @property
    def terminal(self) -> bool:
        return self in (ApprovalStatus.APPROVED, ApprovalStatus.REJECTED,
                        ApprovalStatus.EXPIRED)


class ApprovalTimeoutPolicy:
    """审批超时策略（GAP-19a）：到点升级提醒（沿链逐级）、超时自动过期。

    - ``escalation_chain``：角色升级链（如 ("primary_approver", "sec_admin")），
      按尝试次数逐级通知；链耗尽后等待过期。
    - **判定与执行分离**：本类只做纯判定；谁来 sweep（端口/定时任务）可替换，
      规则本身是可测试、可评审的数据 —— 与状态机同一个哲学。
    """

    def __init__(self, *, pending_ttl_s: float = 300.0,
                 escalate_after_s: float = 60.0,
                 escalation_chain: tuple[str, ...] = ()):
        if escalate_after_s >= pending_ttl_s:
            raise ValueError("升级必须早于过期，否则升级通知永远来不及送达")
        self.pending_ttl_s = pending_ttl_s
        self.escalate_after_s = escalate_after_s
        self.escalation_chain = escalation_chain

    def timeout_state(self, req: "ApprovalRequest", *, now: float) -> str:
        """返回 'expired' | 'escalate:<角色>' | 'waiting'（三态判定，供外层执行副作用）。"""
        if req.status != ApprovalStatus.PENDING.value:
            return "waiting"
        age = now - req.created_at
        if age > self.pending_ttl_s:
            return "expired"
        if self.escalation_chain and age > self.escalate_after_s:
            nxt = self._next_escalation(req)
            if nxt:
                return f"escalate:{nxt}"
        return "waiting"

    def _next_escalation(self, req: "ApprovalRequest") -> str:
        tried = set(req.escalation_history)
        for r in self.escalation_chain:
            if r not in tried:
                return r
        return ""


@dataclass
class ApprovalRequest:
    request_id: str
    run_id: str
    action: str
    params: dict[str, Any]
    risk_level: str = "high"
    status: str = ApprovalStatus.PENDING.value  # pending/approved/rejected/expired
    requested_by: str = "agent"
    created_at: float = field(default_factory=time.time)
    # GAP-19a: 审批运营字段 —— 谁该审、已提醒过谁、为何过期都必须是记录而非口口相传
    approvers: str = "approver"
    escalation_history: list[str] = field(default_factory=list)
    note: str = ""


class ApprovalPort(Protocol):
    """人工审批端口：高风险副作用在执行前必须经由本端口授权。"""

    def request(self, req: ApprovalRequest) -> str: ...
    def resolve(self, request_id: str, decision: ApprovalDecision, by: str) -> None: ...
    def get(self, request_id: str) -> ApprovalRequest: ...


class TaskData(Generic[T]):
    """调度队列中的任务载荷。"""

    def __init__(self, run_id: str, payload: T):
        self.run_id = run_id
        self.payload = payload


class Worker(Protocol):
    def process(self, task: TaskData) -> None: ...


class TaskQueue(Protocol):
    def enqueue(self, run_id: str, queue: str, payload: Any) -> None: ...
    def claim(self, queue: str) -> Optional[TaskData]: ...
    def ack(self, run_id: str) -> None: ...
    def nack(self, run_id: str, requeue: bool = True) -> None: ...


@dataclass
class Action:
    """有副作用的行动 —— 经"提议→校验→授权→审批→执行→验真"闭环。"""

    action_id: str = field(default_factory=lambda: f"act_{uuid.uuid4().hex[:8]}")
    run_id: str = ""
    name: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    risk_level: str = "low"
    idempotency_key: str = ""
    status: str = "proposed"  # proposed -> approved -> executed / compensated
    executed: bool = False
    result: Optional[dict[str, Any]] = None
    approval_required: bool = False

class ApprovalPendingError(Exception):
    """手工审批模式下，工作流在 human_gate 处中断（可恢复暂停）。

    携带动作名与参数，供上层(API/Worker)创建审批单并落库；
    审批通过后以 pre_approved 决策恢复执行 —— 即 HITL 的 interrupt/resume 语义。
    """

    def __init__(self, action: str, params: dict | None = None):
        super().__init__(f"approval pending: {action}")
        self.action = action
        self.params = dict(params or {})
