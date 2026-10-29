# -*- coding: utf-8 -*-
"""服务层共享组件纯逻辑测试（不依赖任何真实中间件）。

覆盖 services/shared/runtime.py（网关三件套 + 内存降级 Provider）与
services/shared/queue.py（通道选择语义）——服务层"mock 化可测"的第一层。
运行：仓库根目录 `python -m pytest tests/test_services_shared.py -q`
"""
import asyncio
import os

import pytest

from services.shared.queue import TaskMessage, consume, enqueue, pulsar_available
from services.shared.runtime import (
    Env,
    IdempotencyGuard,
    InfraProvider,
    MemoryKV,
    RateLimiter,
    RequestContext,
    Settings,
    TokenBucket,
    new_request_context,
)


class TestEnvBool:
    def test_missing_uses_default(self, monkeypatch):
        monkeypatch.delenv("DATAAGENT_TEST_FLAG", raising=False)
        assert Env.bool_("DATAAGENT_TEST_FLAG", True) is True
        assert Env.bool_("DATAAGENT_TEST_FLAG", False) is False

    def test_truthy_variants(self, monkeypatch):
        for v in ("1", "true", "Yes", "ON"):
            monkeypatch.setenv("DATAAGENT_TEST_FLAG", v)
            assert Env.bool_("DATAAGENT_TEST_FLAG") is True
        for v in ("0", "false", "no", "off", "junk"):
            monkeypatch.setenv("DATAAGENT_TEST_FLAG", v)
            assert Env.bool_("DATAAGENT_TEST_FLAG") is False


class TestSettings:
    def test_defaults_local(self, monkeypatch):
        for k in ("RUN_ENV", "DATAAGENT_DATABASE_URL", "DATAAGENT_REDIS_URL"):
            monkeypatch.delenv(k, raising=False)
        s = Settings()
        assert s.run_env == "local"
        assert s.database_url == ""
        assert s.redis_enabled() is False

    def test_redis_enabled_requires_real_url(self, monkeypatch):
        monkeypatch.setenv("DATAAGENT_REDIS_URL", "redis://localhost:6379/0")
        assert Settings().redis_enabled() is True
        monkeypatch.setenv("DATAAGENT_REDIS_URL", "inmemory")
        assert Settings().redis_enabled() is False


class TestRequestContext:
    def test_defaults_and_unique_ids(self):
        a = new_request_context("ten_a", "u1")
        b = new_request_context("ten_a", "u1")
        assert isinstance(a, RequestContext)
        assert a.roles == {"analyst"}
        assert a.request_id != b.request_id  # 每请求唯一

    def test_roles_passthrough(self):
        ctx = new_request_context("ten_a", "u9", roles={"admin", "approver"})
        assert ctx.roles == {"admin", "approver"}


class TestIdempotencyGuard:
    def test_first_acquire_true_second_false(self):
        g = IdempotencyGuard()
        assert g.try_acquire("ten_a", "u1", "key-1") is True
        assert g.try_acquire("ten_a", "u1", "key-1") is False

    def test_different_key_or_tenant_passes(self):
        g = IdempotencyGuard()
        assert g.try_acquire("ten_a", "u1", "k") is True
        assert g.try_acquire("ten_a", "u1", "k2") is True
        assert g.try_acquire("ten_b", "u1", "k") is True  # 租户维度隔离

    def test_ttl_window_expiry(self, monkeypatch):
        g = IdempotencyGuard()
        now = {"t": 1000.0}
        monkeypatch.setattr("services.shared.runtime.time.time", lambda: now["t"])
        assert g.try_acquire("t", "u", "k", ttl_s=10) is True
        now["t"] += 5
        assert g.try_acquire("t", "u", "k", ttl_s=10) is False  # 窗口内
        now["t"] += 6
        assert g.try_acquire("t", "u", "k", ttl_s=10) is True   # 窗口外放行


class TestTokenBucketAndRateLimiter:
    def test_burst_then_deny(self):
        b = TokenBucket(rate=0.0, burst=3)  # 不回填: 3 个突发令牌
        assert [b.allow() for _ in range(3)] == [True, True, True]
        assert b.allow() is False

    def test_rate_limiter_per_tenant_isolation(self):
        rl = RateLimiter(per_tenant_rps=0.0, burst=1)
        assert rl.allow("ten_a") is True
        assert rl.allow("ten_a") is False    # a 打满
        assert rl.allow("ten_b") is True     # b 独立桶不受影响

    def test_refill_over_time(self, monkeypatch):
        now = {"t": 0.0}
        monkeypatch.setattr("services.shared.runtime.time.monotonic", lambda: now["t"])
        b = TokenBucket(rate=10.0, burst=1)
        assert b.allow() is True
        assert b.allow() is False
        now["t"] += 0.2                      # 0.2s * 10rps = 2 个令牌回填
        assert b.allow() is True


class TestMemoryKVAndInfra:
    def test_kv_set_get_delete(self):
        kv = MemoryKV()

        async def run():
            await kv.set("k", "v", ex=60)
            assert await kv.get("k") == "v"
            await kv.delete("k")
            assert await kv.get("k") is None

        asyncio.run(run())

    def test_kv_expiry(self, monkeypatch):
        kv = MemoryKV()
        now = {"t": 1000.0}
        monkeypatch.setattr("services.shared.runtime.time.time", lambda: now["t"])

        async def run():
            await kv.set("k", "v", ex=10)
            now["t"] += 11
            assert await kv.get("k") is None  # 过期即取不到

        asyncio.run(run())

    def test_publish_falls_back_to_memory_queue_and_poll(self):
        for k in ("DATAAGENT_USE_PULSAR", "DATAAGENT_REDIS_URL"):
            os.environ.pop(k, None)
        provider = InfraProvider(Settings())

        async def run():
            assert await provider.publish("topic", {"job": 1}) is True  # 内存降级
            got = await provider.poll(timeout_s=0.0)
            assert got == {"job": 1}
            assert await provider.poll(timeout_s=0.0) is None

        asyncio.run(run())

    def test_graph_and_vector_return_none_without_config(self):
        provider = InfraProvider(Settings())

        async def run():
            assert await provider.get_graph() is None
            assert await provider.get_vector() is None
            kv = await provider.get_cache()  # 无 Redis 配置 → 内存 KV 降级
            assert isinstance(kv, MemoryKV)

        asyncio.run(run())


class TestQueueChannelSemantics:
    def test_pulsar_unavailable_by_default(self, monkeypatch):
        monkeypatch.delenv("DATAAGENT_USE_PULSAR", raising=False)
        import services.shared.queue as q
        q._pulsar_ok = None  # 重置缓存, 强制重判
        assert pulsar_available() is False

    def test_enqueue_returns_false_without_any_channel(self, monkeypatch):
        monkeypatch.delenv("DATAAGENT_USE_PULSAR", raising=False)
        monkeypatch.delenv("DATAAGENT_REDIS_FALLBACK", raising=False)
        import services.shared.queue as q
        q._pulsar_ok = None
        q._SYNC_REDIS = None
        assert enqueue({"job": 1}) is False  # 诚实失败: 无通道可用

    def test_consume_returns_none_when_no_channel(self, monkeypatch):
        monkeypatch.delenv("DATAAGENT_USE_PULSAR", raising=False)
        monkeypatch.delenv("DATAAGENT_REDIS_FALLBACK", raising=False)
        import services.shared.queue as q
        q._pulsar_ok = None
        q._SYNC_REDIS = None
        assert consume(timeout_ms=1) is None

    def test_task_message_ack_nack_callbacks(self):
        calls = {"ack": 0, "nack": 0}
        msg = TaskMessage({"job": 1},
                          ack_fn=lambda: calls.__setitem__("ack", calls["ack"] + 1),
                          nack_fn=lambda: calls.__setitem__("nack", calls["nack"] + 1))
        msg.ack()
        msg.nack()
        assert calls == {"ack": 1, "nack": 1}
        assert TaskMessage({"x"}).ack() is None  # 无回调也安全
