# -*- coding: utf-8 -*-
"""统一执行模型 (Unified Runtime Domain)。

Alignment: 第五篇《Agent Harness 与 Agent Runtime 工程架构篇》
- Run / Step / Attempt / Event / Checkpoint / Run State Machine
- Task, Scheduler, Queue, Worker 基础设施接口
- Human Approval, Side-effect 幂等, 多租户资源
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Generic, Optional, Protocol, TypeVar

T = TypeVar("T")


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


@dataclass
class Run:
    """一个业务任务的完整执行记录 —— 统一 Runtime 语言。"""

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

    def add_event(self, type_: EventType, step_id: str = "", **data: Any) -> Event:
        evt = Event(
            run_id=self.run_id, step_id=step_id, type=type_, data=data
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
        self.status = cp.status
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


class ApprovalDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass
class ApprovalRequest:
    request_id: str
    run_id: str
    action: str
    params: dict[str, Any]
    risk_level: str = "high"
    status: str = "pending"  # pending/approved/rejected
    requested_by: str = "agent"
    created_at: float = field(default_factory=time.time)


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