# -*- coding: utf-8 -*-
"""路由能力硬过滤（GAP-06）与执行器 deadline（GAP-01）测试。

- 能力硬过滤：不支持所需能力的候选**先排除并记录原因**，而不是等调用失败；
- RoutingDecision.excluded 是可解释性的一等输出（第 12 课遗留的兑现）；
- deadline：注入 monotonic 后可**确定性**验证"已过期 → 零次尝试"与
  "重试中途终止"两条语义（真实等待是 flaky 之源）；
- 耗尽重试的异常必须携带最后尝试的模型（第 20 课登记缺陷的修复钉住）。
"""
import pytest

from dataagent.adapters.llm.fake_client import FakeLlmClient
from dataagent.contracts.model import (
    CallStatus,
    LogicalCall,
    Message,
    ModelCapability,
    Role,
)
from dataagent.infra.gateway.llm_runtime import (
    LlmError,
    ModelRegistry,
    ReliableExecutor,
    Router,
)


def make_call(model: str = "demo", task: str = "sql") -> LogicalCall:
    reg = ModelRegistry()
    reg.register(ModelCapability(model=model))
    return LogicalCall.new(
        task=task, capability=reg.resolve(model),
        messages=[Message(role=Role.USER, content="x")],
    )


class TestCapabilityHardFilter:
    def _registry(self) -> ModelRegistry:
        reg = ModelRegistry()
        reg.register(ModelCapability(model="with-tools", supports_tool_calling=True))
        reg.register(ModelCapability(model="no-tools", supports_tool_calling=False))
        return reg

    def test_candidate_without_capability_is_excluded_with_reason(self):
        rt = Router(self._registry())
        rt.add_route("sql", ["no-tools", "with-tools"])
        d = rt.decide("sql", require_capabilities=("tool_calling",))
        assert d.chosen == "with-tools"
        assert ("no-tools", "capability_missing:tool_calling") in d.excluded
        assert "排除" in d.reason and "capability_missing" in d.reason

    def test_add_route_registers_persistent_requirements(self):
        rt = Router(self._registry())
        rt.add_route("sql", ["no-tools", "with-tools"], require_capabilities=("tool_calling",))
        assert rt.capabilities_for("sql") == ("tool_calling",)
        d = rt.decide("sql")  # 不再传参也生效 —— 契约在装配期声明
        assert d.chosen == "with-tools"

    def test_all_candidates_excluded_is_fail_fast_and_unretryable(self):
        rt = Router(ModelRegistry())  # 空注册表
        rt.add_route("x", ["ghost1", "ghost2"], require_capabilities=("tool_calling",))
        with pytest.raises(LlmError) as ei:
            rt.decide("x")
        assert ei.value.retryable is False
        assert "ghost1:model_not_registered" in str(ei.value)

    def test_unknown_capability_name_fails_fast(self):
        with pytest.raises(ValueError, match="未知能力名"):
            self._registry().resolve("with-tools").supports("tool_calling_typo")

    def test_reason_includes_exclusion_detail(self):
        """第 12 课遗留兑现：reason 含"为什么排除其他候选"。"""
        rt = Router(self._registry())
        rt.add_route("sql", ["no-tools", "with-tools"])
        d = rt.decide("sql", require_capabilities=("tool_calling",))
        assert d.reason.startswith("task=sql")
        assert "no-tools(capability_missing:tool_calling)" in d.reason


class _AdvancingClock:
    """受控单调时钟：sleep 会真实推进时钟 —— 退避与 deadline 联动可确定性断言。"""

    def __init__(self, start: float = 0.0):
        self.now = start

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class TestDeadlineInterception:
    def _executor(self, client: FakeLlmClient, clock: _AdvancingClock,
                  max_attempts: int = 3, base_backoff: float = 0.4) -> ReliableExecutor:
        reg = ModelRegistry()
        reg.register(ModelCapability(model="demo"))
        rt = Router(reg)
        rt.add_route("sql", ["demo"])
        return ReliableExecutor(
            client, rt, reg,
            max_attempts=max_attempts, base_backoff_s=base_backoff,
            sleep=clock.sleep, monotonic=clock.monotonic,
        )

    def test_deadline_already_past_means_zero_attempts(self):
        """截止时间已过 → 零次尝试（参照工程钉住的同款语义）。"""
        clock = _AdvancingClock(start=100.0)
        client = FakeLlmClient()
        ex = self._executor(client, clock)
        call = make_call()
        with pytest.raises(LlmError) as ei:
            ex.complete(call, deadline=50.0)  # 100 >= 50 → 已过期
        assert ei.value.retryable is False
        assert client.call_count == 0          # 一次都没打
        assert ex.stats.timeouts == 1
        assert call.status is CallStatus.TIMED_OUT

    def test_deadline_stops_retrying_midway(self):
        """重试中途越过截止时间 → 停止（不再耗尽 max_attempts）。"""
        clock = _AdvancingClock(start=0.0)
        client = FakeLlmClient(fail_times=9)   # 持续故障
        ex = self._executor(client, clock, max_attempts=10, base_backoff=0.4)
        call = make_call()
        with pytest.raises(LlmError) as ei:
            ex.complete(call, deadline=0.5)
        # 0.4 < 0.5 允许第2次尝试; 第2次失败后 sleep 到 0.8 >= 0.5 → 终止
        assert ei.value.retryable is False
        assert "deadline 已到" in str(ei.value)
        assert client.call_count == 2          # 不会打满 10 次
        assert ex.stats.timeouts == 1

    def test_deadline_not_hit_runs_to_success(self):
        clock = _AdvancingClock(start=0.0)
        client = FakeLlmClient(fail_times=1)
        ex = self._executor(client, clock, base_backoff=0.1)
        call = make_call()
        result = ex.complete(call, deadline=10.0)
        assert result.text
        assert ex.stats.timeouts == 0

    def test_exhaustion_error_carries_last_model(self):
        """第 20 课登记缺陷的修复钉住：耗尽异常必须含最后尝试的模型名。"""
        clock = _AdvancingClock(start=0.0)
        client = FakeLlmClient(fail_times=9)
        ex = self._executor(client, clock, max_attempts=2)
        call = make_call()
        with pytest.raises(LlmError) as ei:
            ex.complete(call)
        assert "[最后尝试模型: demo]" in str(ei.value)
        assert call.attempts[-1].status is CallStatus.FAILED
