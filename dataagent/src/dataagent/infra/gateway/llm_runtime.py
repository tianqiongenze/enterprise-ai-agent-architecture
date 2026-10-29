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
from typing import Any, Callable, Optional

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
    """统一的模型调用异常。

    ``retry_after_s``（GAP-13 借鉴：限流型故障）：服务端指示的退避秒数（429
    Retry-After 语义）。执行器优先采用服务端指示而非本地指数退避——
    "听上游的"比"猜上游的"省配额也少等待。
    """

    def __init__(self, message: str, retryable: bool = True, attempt: int = 0,
                 retry_after_s: Optional[float] = None):
        super().__init__(message)
        self.retryable = retryable
        self.attempt = attempt
        self.message = message
        self.retry_after_s = retry_after_s


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
    excluded: list[tuple[str, str]] = field(default_factory=list)  # (模型, 排除原因)——可解释性一等输出


class Router:
    """按 TaskProfile 选择模型；失败时按顺序 Fallback。

    能力硬过滤（GAP-06）：``decide`` 支持 ``require_capabilities`` ——
    不支持所需能力的候选**直接排除并记录原因**，而不是等调用失败后才暴露。
    这落实"能力先于成本"的路由宪法：能力不匹配的模型进任务 = 静默失败。
    """

    def __init__(self, registry: ModelRegistry):
        self._registry = registry
        # task -> 候选模型列表（有序，第一个为首选）
        self._routes: dict[str, list[str]] = {}
        # task -> 能力硬性要求（add_route(require_capabilities=...) 登记）
        self._route_capabilities: dict[str, tuple[str, ...]] = {}

    def add_route(
        self, task: str, models: list[str], require_capabilities: tuple[str, ...] = ()
    ) -> None:
        """登记路由：候选链 + 该任务的能力硬性要求（可空）。"""
        self._routes[task] = list(models)
        if require_capabilities:
            self._route_capabilities[task] = tuple(require_capabilities)

    def capabilities_for(self, task: str) -> tuple[str, ...]:
        return self._route_capabilities.get(task, ())

    def decide(
        self, task: str, *, require_capabilities: Optional[tuple[str, ...]] = None
    ) -> RoutingDecision:
        caps = tuple(require_capabilities) if require_capabilities is not None else self._route_capabilities.get(task, ())
        candidates = self._routes.get(task) or ["default"]
        available: list[str] = []
        excluded: list[tuple[str, str]] = []
        for c in candidates:
            if not self._registry.has(c):
                excluded.append((c, "model_not_registered"))
                continue
            cap = self._registry.resolve(c)
            missing = [x for x in caps if not cap.supports(x)]
            if missing:
                excluded.append((c, f"capability_missing:{'+'.join(missing)}"))
                continue
            available.append(c)
        if not available:
            detail = "; ".join(f"{m}:{r}" for m, r in excluded) or "候选链为空"
            raise LlmError(f"任务 {task} 无可用模型（{detail}）", retryable=False)
        reason = f"task={task}"
        if excluded:
            reason += "; 排除: " + "; ".join(f"{m}({r})" for m, r in excluded)
        return RoutingDecision(chosen=available[0], fallbacks=available[1:], reason=reason, excluded=excluded)


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
        sleep: Any = time.sleep,
        monotonic: Optional[Callable[[], float]] = None,
    ):
        self._client = client
        self._router = router
        self._registry = registry
        self.max_attempts = max_attempts
        self.timeout_s = timeout_s
        self.base_backoff_s = base_backoff_s
        # 退避等待可注入：测试注入空实现即可确定性验证重试语义（防 flaky）
        self._sleep = sleep
        # 单调时钟可注入（GAP-01）：deadline 拦截语义可被确定性验证，
        # 不依赖真实等待（参照工程 monotonic 注入的同款设计）
        self._monotonic: Callable[[], float] = monotonic or time.monotonic
        self.stats = CallStats()

    @property
    def registry(self) -> ModelRegistry:
        """公开只读访问器 —— 上游（Harness 等）不应触碰私有字段 ``_registry``。"""
        return self._registry

    @property
    def router(self) -> Router:
        return self._router

    def emit(self, owner: LogicalCall, event: EventType, **data: Any) -> Event:
        return Event(event_id=f"evt_{uuid.uuid4().hex[:10]}", type=event, data=data)

    def complete(
        self,
        call: LogicalCall,
        *,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        structured: Optional[type] = None,
        deadline: Optional[float] = None,
    ) -> CompletionResult:
        """执行整个 LogicalCall：内部重试 + fallback + 结构化校验 + deadline 拦截。

        语义：每次 Attempt 按候选模型顺序尝试；失败则记为该 Attempt 失败，
        进入下一次 Attempt（重试同一候选，或落到 Fallback），直到成功或耗尽 max_attempts。

        deadline（GAP-01）：**单调时钟瞬时值**（调用方用注入的 monotonic 计算），
        每次尝试开始前检查——已过期则立即终止（retryable=False），不再发起新尝试；
        耗尽重试预算同样按"截止时间语义"失败并计入 ``stats.timeouts``。
        注意：同步客户端无法强杀挂起中的调用，deadline 拦的是"重试终止"；
        强杀语义需要线程池/异步化（已登记为后续项）。
        """
        decision = self._router.decide(call.task)
        attempt_models = [decision.chosen] + decision.fallbacks

        last_error: Optional[LlmError] = None
        last_model = decision.chosen
        for attempt_idx in range(self.max_attempts):
            # deadline 拦截：在发起任何新尝试之前检查（"截止时间已过 → 零次尝试"可被确定性断言）
            if deadline is not None and self._monotonic() >= deadline:
                self.stats.timeouts += 1
                call.status = CallStatus.TIMED_OUT
                raise LlmError(
                    f"deadline 已到，终止重试（已尝试至模型 {last_model}，attempt {attempt_idx}）",
                    retryable=False,
                )
            for model in attempt_models:
                self.stats.calls += 1
                last_model = model
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
                    # 退避选择（GAP-13 借鉴）：服务端指示优先（429 Retry-After），否则本地指数退避封顶
                    wait = (min(e.retry_after_s, 1.0) if e.retry_after_s is not None
                            else min(self.base_backoff_s * (2 ** attempt_idx), 1.0))
                    self._sleep(wait)
                except Exception as e:  # noqa: BLE001
                    last_error = LlmError(str(e), retryable=True)
                    self.stats.failures += 1
                    self.stats.retries += 1
                    call.attempts.append(
                        self._flatten_attempt(attempt_idx, CallStatus.FAILED, start, None, model, str(e))
                    )
                    self._sleep(self.base_backoff_s)

        call.status = CallStatus.FAILED
        # 耗尽重试：异常必须携带最后尝试的模型（第 20 课登记缺陷的修复——排障可定位）
        raise LlmError(
            f"{last_error.message if last_error else '模型调用失败'} [最后尝试模型: {last_model}]",
            retryable=True,
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