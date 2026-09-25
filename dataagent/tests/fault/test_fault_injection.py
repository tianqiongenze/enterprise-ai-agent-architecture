# -*- coding: utf-8 -*-
"""故障注入测试 (第五篇第6课 + 第四篇第3课)。

专门验证 Runtime 在真实故障下的可靠性：
- 模型上游反复失败 → 重试/降级后仍成功
- 单元层面验证 Attempt 生命周期与状态语义
"""
import pytest

from dataagent.adapters.llm.fake_client import FakeLlmClient
from dataagent.contracts.model import CallStatus, LogicalCall, Message, ModelCapability, Role
from dataagent.infra.gateway.llm_runtime import LlmError, ModelRegistry, ReliableExecutor, Router


@pytest.fixture
def failing_then_ok():
    reg = ModelRegistry()
    reg.register(ModelCapability(model="default"))
    reg.register(ModelCapability(model="luna"))
    router = Router(reg)
    router.add_route("ana", ["luna", "default"])
    client = FakeLlmClient(handler=lambda m, c: "恢复后的结果", fail_times=2)
    return ReliableExecutor(client, router, reg, max_attempts=4, base_backoff_s=0.001), client


class TestFaultInjection:
    def test_recovers_after_failures(self, failing_then_ok):
        exe, client = failing_then_ok
        call = LogicalCall.new(
            "ana", exe._router._registry.resolve("default"),
            [Message(role=Role.USER, content="x")], max_attempts=4,
        )
        res = exe.complete(call)
        assert res.text == "恢复后的结果"
        assert client.fail_times == 0
        assert exe.stats.retries == 2

    def test_attempt_lifecycle_recorded(self, failing_then_ok):
        exe, client = failing_then_ok
        call = LogicalCall.new(
            "ana", exe._router._registry.resolve("default"),
            [Message(role=Role.USER, content="x")], max_attempts=4,
        )
        exe.complete(call)
        # 至少有一次失败的尝试 + 一次成功
        statuses = [a.status for a in call.attempts]
        assert CallStatus.FAILED in statuses
        assert CallStatus.SUCCEEDED in statuses

    def test_unrecoverable_raises(self):
        reg = ModelRegistry(); reg.register(ModelCapability(model="default"))
        router = Router(reg); router.add_route("ana", ["default"])
        client = FakeLlmClient(fail_times=99)
        exe = ReliableExecutor(client, router, reg, max_attempts=2, base_backoff_s=0.001)
        call = LogicalCall.new("ana", exe._router._registry.resolve("default"), [Message(role=Role.USER, content="x")], max_attempts=2)
        with pytest.raises(LlmError):
            exe.complete(call)
        assert call.status == CallStatus.FAILED


class TestIdempotency:
    def test_side_effect_not_repeated(self):
        from dataagent.infra.runtime.workflow import IdempotencyStore
        idem = IdempotencyStore()
        assert idem.try_mark("oid:1") is True
        assert idem.try_mark("oid:1") is False  # 幂等：第二次不再执行
        assert idem.try_mark("oid:2") is True