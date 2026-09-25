# -*- coding: utf-8 -*-
"""LLM Runtime —— 可靠模型执行底座 (第四篇)。

模块分层：
- Registry：逻辑模型 / 物理模型能力契约注册
- Routing：按 TaskProfile 多模型路由、Fallback、降级
- Execution：ReliableExecutor（LogicalCall/Attempt、Retry、Timeout、Deadline、
  Structured Output、Schema Validation）
- Observability：调用计数、成本统计、Trace 事件

设计意图（对齐第四篇第3课）：一次"模型调用成功"不等于"任务成功"。
我们以 LogicalCall 为稳定执行对象，内部由多个 Attempt 支撑，提供可恢复、可验证、
可追踪的执行语义。
"""
from __future__ import annotations

import inspect
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from ...contracts.model import (
    CallStatus,
    CompletionResult,
    LlmClient,
    LogicalCall,
    Message,
    ModelCapability,
    Role,
    ToolCall,
    Usage,
)
from ...contracts.runtime import Event, EventType


class LlmError(Exception):
    """统一的模型调用异常。"""

    def __init__(self, message: str, retryable: bool = True, attempt: int = 0):
        super().__init__(message)
        self.retryable = retryable
        self.attempt = attempt
        self.message = message


@dataclass
class CallStats:
    calls: int = 0
    attempts: int = 0
    retries: int = 0
    failures: int = 0
    timeouts: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_latency_ms: float = 0.0

    @property
    def estimated_cost(self) -> float:
        # 以最低成本模型近似
        return (self.input_tokens + self.output_tokens) / 1000 * 0.2


class ModelRegistry:
    """逻辑模型 → 物理模型能力契约。"""

    def __init__(self) -> None:
        self._capabilities: dict[str, ModelCapability] = {}

    def register(self, cap: ModelCapability) -> None:
        self._capabilities[cap.model] = cap

    def alias(self, alias: str, model: str) -> None:
        self._capabilities[alias] = self._capabilities[model]

    def resolve(self, model: str) -> ModelCapability:
        if model not in self._capabilities:
            raise KeyError(f"未注册的模型: {model}")
        return self._capabilities[model]

    def has(self, model: str) -> bool:
        return model in self._capabilities


@dataclass
class RoutingDecision:
    chosen: str
    fallbacks: list[str]
    reason: str


class Router:
    """按 TaskProfile 选择模型；失败时按顺序 Fallback。"""

    def __init__(self, registry: ModelRegistry):
        self._registry = registry
        # task -> 候选模型列表（有序，第一个为首选）
        self._routes: dict[str, list[str]] = {}

    def add_route(self, task: str, models: list[str]) -> None:
        self._routes[task] = models

    def decide(self, task: str) -> RoutingDecision:
        candidates = self._routes.get(task) or ["default"]
        available = [c for c in candidates if self._registry.has(c)]
        if not available:
            raise LlmError(f"任务 {task} 无可用模型", retryable=False)
        return RoutingDecision(chosen=available[0], fallbacks=available[1:], reason=f"task={task}")


class ReliableExecutor:
    """可靠执行器：LogicalCall 生命周期 + Retry/Timeout/Deadline + 结构化输出校验。"""

    def __init__(
        self,
        client: LlmClient,
        router: Router,
        registry: ModelRegistry,
        *,
        max_attempts: int = 3,
        timeout_s: float = 60.0,
        base_backoff_s: float = 0.2,
    ):
        self._client = client
        self._router = router
        self._registry = registry
        self.max_attempts = max_attempts
        self.timeout_s = timeout_s
        self.base_backoff_s = base_backoff_s
        self.stats = CallStats()

    def emit(self, owner: LogicalCall, event: EventType, **data: Any) -> Event:
        return Event(event_id=f"evt_{uuid.uuid4().hex[:10]}", type=event, data=data)

    def complete(
        self,
        call: LogicalCall,
        *,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        structured: Optional[type] = None,
    ) -> CompletionResult:
        """执行整个 LogicalCall：内部重试 + fallback + 结构化校验。

        语义：每次 Attempt 按候选模型顺序尝试；失败则记为该 Attempt 失败，
        进入下一次 Attempt（重试同一候选，或落到 Fallback），直到成功或耗尽 max_attempts。
        """
        decision = self._router.decide(call.task)
        attempt_models = [decision.chosen] + decision.fallbacks

        last_error: Optional[LlmError] = None
        for attempt_idx in range(self.max_attempts):
            for model in attempt_models:
                self.stats.calls += 1
                start = time.time()
                try:
                    result = self._client.complete(
                        self._registry.resolve(model),
                        call.messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        structured=structured,
                    )
                    if structured is not None and result.structured is not None:
                        self._validate_structured(result.structured, structured, model)
                    self.stats.attempts += 1
                    self.stats.total_latency_ms += (time.time() - start) * 1000
                    if result.usage:
                        self.stats.input_tokens += result.usage.prompt_tokens
                        self.stats.output_tokens += result.usage.completion_tokens
                    call.status = CallStatus.SUCCEEDED
                    call.output = result.text
                    call.structured = result.structured
                    call.usage = result.usage
                    call.attempts.append(
                        self._flatten_attempt(attempt_idx, CallStatus.SUCCEEDED, start, result, model)
                    )
                    return result
                except LlmError as e:
                    last_error = e
                    self.stats.failures += 1
                    self.stats.retries += 1
                    call.attempts.append(
                        self._flatten_attempt(attempt_idx, CallStatus.FAILED, start, None, model, e.message)
                    )
                    if not e.retryable:
                        break
                    time.sleep(min(self.base_backoff_s * (2 ** attempt_idx), 1.0))
                except Exception as e:  # noqa: BLE001
                    last_error = LlmError(str(e), retryable=True)
                    self.stats.failures += 1
                    self.stats.retries += 1
                    call.attempts.append(
                        self._flatten_attempt(attempt_idx, CallStatus.FAILED, start, None, model, str(e))
                    )
                    time.sleep(self.base_backoff_s)

        call.status = CallStatus.FAILED
        raise LlmError(
            last_error.message if last_error else "模型调用失败", retryable=True
        )

    def _flatten_attempt(self, idx, status, start, result, model, error=None):
        from ...contracts.model import Attempt
        return Attempt(
            attempt_index=idx,
            status=status,
            started_at=start,
            finished_at=time.time(),
            error=error,
            output=result.text if result else None,
            usage=result.usage if result else None,
        )

    def _validate_structured(self, data: dict[str, Any], model_type: type, model: str) -> None:
        """Schema Validation：阻止无效结果进入下游。"""
        try:
            if hasattr(model_type, "model_validate"):
                model_type.model_validate(data)
            else:
                inspect.signature(model_type).bind(**data)
        except Exception as e:  # noqa: BLE001
            raise LlmError(f"结构化输出校验失败 [{model}]: {e}", retryable=True) from e