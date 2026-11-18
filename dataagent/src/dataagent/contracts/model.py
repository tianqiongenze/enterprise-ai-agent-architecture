"""模型调用契约 (LLM Runtime 契约)。

Alignment: 第四篇《LLM 执行底座篇》
- LogicalCall / Attempt: 一次模型调用的统一生命周期模型
- ModelCapability / TaskProfile: 逻辑模型与物理模型分层路由
- 意图定义：Runtime 是 Agent Harness 的"执行底座"，业务代码不得再直接依赖具体模型 SDK。
"""
from __future__ import annotations

import time
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Protocol


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True)
class Message:
    role: Role
    content: str = ""
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: Sequence[ToolCall] | None = None


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ModelCapability:
    """一个物理模型的能力契约，用于路由决策。"""

    model: str
    supports_tool_calling: bool = True
    supports_structured_output: bool = True
    supports_streaming: bool = True
    supports_reasoning: bool = False
    max_context_tokens: int = 128000
    max_output_tokens: int = 8192
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    latency_p50_ms: float = 0.0
    provider: str = "mock"

    #: 能力名 → 契约属性（能力硬过滤 GAP-06 的判定表）
    _CAPABILITY_ATTRS: ClassVar[dict[str, str]] = {
        "tool_calling": "supports_tool_calling",
        "structured_output": "supports_structured_output",
        "streaming": "supports_streaming",
        "reasoning": "supports_reasoning",
    }

    def supports(self, capability: str) -> bool:
        """按能力名判定是否支持（硬过滤判定入口）。

        未知能力名直接抛错（fail-fast）——拼写错误静默返回 False 会让
        候选链"看起来健康"地全部被排除。
        """
        attr = ModelCapability._CAPABILITY_ATTRS.get(capability)
        if attr is None:
            raise ValueError(
                f"未知能力名: {capability}（可用: {sorted(ModelCapability._CAPABILITY_ATTRS)}）"
            )
        return bool(getattr(self, attr))


class CallStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELED = "canceled"


@dataclass
class LogicalCall:
    """一次逻辑模型调用：可被重试为多个 Attempt，是一个"稳定的执行对象"。"""

    call_id: str
    task: str
    capability: ModelCapability
    messages: list[Message]
    created_at: float = field(default_factory=time.time)
    attempts: list[Attempt] = field(default_factory=list)
    status: CallStatus = CallStatus.PENDING
    output: str | None = None
    structured: dict[str, Any] | None = None
    usage: Usage | None = None
    max_attempts: int = 3
    deadline: float = 0.0

    @staticmethod
    def new(
        task: str,
        capability: ModelCapability,
        messages: list[Message],
        max_attempts: int = 3,
        deadline: float = 0.0,
    ) -> LogicalCall:
        return LogicalCall(
            call_id=f"call_{uuid.uuid4().hex[:12]}",
            task=task,
            capability=capability,
            messages=messages,
            max_attempts=max_attempts,
            deadline=deadline or time.time() + 60,
        )


@dataclass
class Attempt:
    """一次具体的外部模型请求。LogicalCall 由若干个 Attempt 组成。"""

    attempt_index: int
    status: CallStatus
    started_at: float
    finished_at: float | None = None
    error: str | None = None
    output: str | None = None
    structured: dict[str, Any] | None = None
    usage: Usage | None = None


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @property
    def input_cost(self) -> float:
        return self.prompt_tokens / 1000


class CompletionFn(Protocol):
    """对外部 LLM 的单次调用 (Attempt) 接口。"""

    def __call__(
        self,
        capability: ModelCapability,
        messages: Sequence[Message],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        structured: type | None = None,
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> CompletionResult: ...


@dataclass(frozen=True)
class CompletionResult:
    text: str
    tool_calls: Sequence[ToolCall] = ()
    usage: Usage | None = None
    model: str = "mock"
    reasoning: str | None = None
    structured: dict[str, Any] | None = None


class LlmClient(Protocol):
    """统一模型调用入口 —— 上层 Agent 只依赖本协议，不感知具体模型。"""

    def complete(
        self,
        capability: ModelCapability,
        messages: Sequence[Message],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        structured: type | None = None,
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> CompletionResult: ...

    def stream(
        self,
        capability: ModelCapability,
        messages: Sequence[Message],
        **kwargs: Any,
    ) -> Iterable[str]: ...
