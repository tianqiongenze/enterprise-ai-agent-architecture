# -*- coding: utf-8 -*-
"""单元测试 —— LLM Runtime：路由、可靠执行、故障注入 (第四篇)。"""
import pytest

from dataagent.adapters.llm.fake_client import FakeLlmClient
from dataagent.contracts.model import (
    CallStatus,
    LogicalCall,
    Message,
    ModelCapability,
    Role,
)
from dataagent.infra.gateway.llm_runtime import LlmError, ModelRegistry, ReliableExecutor, Router


def build_runtime(handler=None, fail_times=0):
    reg = ModelRegistry()
    reg.register(ModelCapability(model="default", provider="mock"))
    reg.register(ModelCapability(model="luna", provider="mock"))
    router = Router(reg)
    router.add_route("planning", ["default"])
    router.add_route("fallback_route", ["nope", "default"])
    client = FakeLlmClient(handler=handler, fail_times=fail_times)
    exe = ReliableExecutor(client, router, reg, max_attempts=3, base_backoff_s=0.001)
    return exe, client, reg, router


def call_for(exe, task, messages=None, hits=None):
    return LogicalCall.new(
        task, exe._router._registry.resolve("default"), messages or [Message(role=Role.USER, content="hi")], hits
    )


class TestRouting:
    def test_router_chooses(self):
        _, _, _, router = build_runtime()
        d = router.decide("planning")
        assert d.chosen == "default"

    def test_router_fallback_available(self):
        _, _, _, router = build_runtime()
        d = router.decide("fallback_route")
        assert d.chosen == "default"
        assert "nope" not in d.fallbacks  # 未注册模型被过滤

    def test_router_no_route_defaults(self):
        _, _, _, router = build_runtime()
        d = router.decide("unknown_task")
        assert d.chosen == "default"


class TestReliableExecution:
    def test_success(self):
        exe, client, _, _ = build_runtime(handler=lambda msgs, c: "ок答案")
        call = LogicalCall.new(
            "planning", exe._router._registry.resolve("default"),
            [Message(role=Role.USER, content="hi")], max_attempts=2
        )
        res = exe.complete(call)
        assert res.text
        assert call.status == CallStatus.SUCCEEDED
        assert call.output == "ок答案"

    def test_retries_then_recovers(self):
        # fail_times=1 → 第一次失败，重试成功
        exe, client, _, _ = build_runtime(handler=lambda msgs, c: "最终结果", fail_times=1)
        call = call_for(exe, "planning")
        res = exe.complete(call)
        assert res.text == "最终结果"
        assert exe.stats.retries == 1
        assert len(call.attempts) >= 2

    def test_exhausts_retries_raises(self):
        exe, client, _, _ = build_runtime(handler=lambda msgs, c: "x", fail_times=99)
        exe.max_attempts = 2
        call = call_for(exe, "planning")
        with pytest.raises(LlmError):
            exe.complete(call)
        assert call.status == CallStatus.FAILED

    def test_structured_output_validation(self):
        from pydantic import BaseModel

        class Plan(BaseModel):
            steps: list[str]
            conclusion: str

        exe, client, _, _ = build_runtime()
        # fake client 结构化 handler 默认返回所有 required 字段
        call = call_for(exe, "planning")
        res = exe.complete(call, structured=Plan)
        assert res.structured is not None
        # 它经过 Schema Validation -> pydantic 校验通过
        Plan.model_validate(res.structured)


class TestStatsAndObservability:
    def test_stats_recorded(self):
        exe, client, _, _ = build_runtime(handler=lambda msgs, c: "结果", fail_times=1)
        for _ in range(3):
            exe.complete(call_for(exe, "planning"))
        # 3 次成功 + 首次调用耗尽的 1 次失败重试（calls 计数包含失败尝试）
        assert exe.stats.attempts == 3
        assert exe.stats.retries >= 1
        assert exe.stats.input_tokens > 0
        assert exe.stats.estimated_cost >= 0