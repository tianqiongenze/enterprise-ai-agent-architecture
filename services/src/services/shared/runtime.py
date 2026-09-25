# -*- coding: utf-8 -*-
"""共享运行时/配置层 (RUNTIME + Provider)。

作为连接“dataagent 内核(纯离线)” 与 “企业级服务层(中间件)” 的桥梁：
- 提供统一配置(Pydantic Settings)，从 env/configs 读取
- Provider 工厂：Pulsar/CockroachDB/Redis/Nebula/Milvus —— 均为异步型、可降级到内存
- 网关层：请求 ID、幂等、限流(简单漏桶)、租户上下文
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field


# ---------------- 配置 ----------------
class Env(str):  # 兼容从 env 读布尔
    @staticmethod
    def bool_(name: str, default: bool = False) -> bool:
        v = os.getenv(name)
        if v is None:
            return default
        return v.strip().lower() in ("1", "true", "yes", "on")


class Settings(BaseModel):
    """统一配置（前端/多端/worker 共用）。"""

    app_name: str = "dataagent"
    run_env: str = Field(default_factory=lambda: os.getenv("RUN_ENV", "local"))
    use_pulsar: bool = Field(default_factory=lambda: Env.bool_("DATAAGENT_USE_PULSAR", False))

    database_url: str = Field(default_factory=lambda: os.getenv("DATAAGENT_DATABASE_URL", ""))
    redis_url: str = Field(default_factory=lambda: os.getenv("DATAAGENT_REDIS_URL", ""))
    pulsar_url: str = Field(default_factory=lambda: os.getenv("DATAAGENT_PULSAR_URL", ""))
    pulsar_topic: str = Field(default_factory=lambda: os.getenv("DATAAGENT_PULSAR_TOPIC", "persistent://dataagent/prod/dataagent-jobs"))
    nebula_addr: str = Field(default_factory=lambda: os.getenv("DATAAGENT_NEBULA_ADDR", ""))
    milvus_uri: str = Field(default_factory=lambda: os.getenv("DATAAGENT_MILVUS_URI", ""))

    model_default: str = Field(default_factory=lambda: os.getenv("DATAAGENT_MODEL_DEFAULT", "luna"))
    max_attempts: int = Field(default_factory=lambda: int(os.getenv("DATAAGENT_MAX_ATTEMPTS", "3")))

    def redis_enabled(self) -> bool:
        return bool(self.redis_url) and not self.redis_url.startswith("inmemory")
    def has_infra(self) -> bool:
        return not self.run_env == "local" or self.use_pulsar


# ---------------- 租户上下文 ----------------
@dataclass
class RequestContext:
    request_id: str
    tenant_id: str
    user_id: str
    roles: set[str]
    arrived_at: float = field(default_factory=time.time)


def new_request_context(tenant_id: str, user_id: str, roles: set[str] | None = None) -> RequestContext:
    return RequestContext(
        request_id=f"req_{uuid.uuid4().hex[:10]}",
        tenant_id=tenant_id,
        user_id=user_id,
        roles=roles or {"analyst"},
    )


# ---------------- 网关：幂等 / 限流 ----------------
class IdempotencyGuard:
    """幂等：同一 (tenant, user, idempotency_key) 在窗口内只放行一次。"""

    def __init__(self, store: Optional[dict] = None):
        self._store: dict[str, float] = store if store is not None else {}

    def _key(self, tenant: str, user: str, ikey: str) -> str:
        raw = f"{tenant}|{user}|{ikey}"
        return hashlib.sha256(raw.encode()).hexdigest()[:24]

    def try_acquire(self, tenant: str, user: str, ikey: str, ttl_s: float = 300) -> bool:
        k = self._key(tenant, user, ikey)
        now = time.time()
        if k in self._store and now - self._store[k] < ttl_s:
            return False  # 重复请求
        self._store[k] = now
        return True


class TokenBucket:
    """漏桶限流（每租户 RPS）。生产可替换为 Redis + Lua 原子限流。"""

    def __init__(self, rate: float, burst: float):
        self.rate = rate
        self.burst = burst
        self.tokens = burst
        self.updated = time.monotonic()

    def allow(self) -> bool:
        now = time.monotonic()
        self.tokens = min(self.burst, self.tokens + (now - self.updated) * self.rate)
        self.updated = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


class RateLimiter:
    def __init__(self, per_tenant_rps: float = 50, burst: float = 200):
        self._buckets: dict[str, TokenBucket] = {}
        self.per_tenant_rps = per_tenant_rps
        self.burst = burst

    def allow(self, tenant_id: str) -> bool:
        b = self._buckets.get(tenant_id)
        if b is None:
            b = TokenBucket(self.per_tenant_rps, self.burst)
            self._buckets[tenant_id] = b
        return b.allow()


# ---------------- 异步基础设施 Provider（可降级到内存） ----------------
class InfraProvider:
    """提供统一的中间件访问；在 local/未安装依赖时降级为内存实现。

    这样：本地离线可跑全部测试；生产(安装了驱动，run_env!=local)自动使用真实
    Pulsar/CRDB/Redis/Nebula/Milvus。
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._redis = None
        self._nebulia = None
        self._milvus = None
        self._pulsar_producer = None
        self._mem_queue: list[Any] = []   # 本地内存队列(降级)

    # ---- Redis ----
    async def get_cache(self):
        if self.settings.redis_enabled():
            try:
                import redis.asyncio as aioredis
                if self._redis is None:
                    self._redis = aioredis.from_url(self.settings.redis_url, decode_responses=True)
                return self._redis
            except Exception:  # pragma: no cover
                pass
        # 内存缓存降级
        return MemoryKV()

    # ---- Nebula ----
    async def get_graph(self):
        """返回 Nebula 图库客户端（未启用则 None）。"""
        if not self.settings.nebula_addr:
            return None
        try:
            import nebula3.gclient.net as nebula_net
            nebula_net.ConnectionPool
            return {"addr": self.settings.nebula_addr}  # 真实连接在 worker 中建立
        except Exception:  # pragma: no cover
            return None

    # ---- Milvus ----
    async def get_vector(self):
        if not self.settings.milvus_uri:
            return None
        try:
            from pymilvus import connections
            connections.connect(alias="dataagent", uri=self.settings.milvus_uri)
            return {"connected": True}
        except Exception:  # pragma: no cover
            return None

    # ---- Pulsar 生产者（异步）----
    async def publish(self, topic: str, payload: dict) -> bool:
        if self.settings.use_pulsar:
            try:
                import pulsar  # sync client，包在 executor 中
                # 真实 Pulsar 生产用阻塞客户端在 worker 线程池；这里提供统一的协议签名
                self._pulsar_client = self._pulsar_client or pulsar.Client(self.settings.pulsar_url)
                producer = self._pulsar_client.create_producer(topic)
                producer.send(("dataagent-payload-v1") + "\x00" + bytes(str(payload), "utf-8"))
                return True
            except Exception:  # pragma: no cover
                return False
        self._mem_queue.append(payload)
        return True

    async def poll(self, timeout_s: float = 1.0) -> Optional[Any]:
        """本地内存队列消费者（降级）。"""
        await asyncio.sleep(timeout_s)
        if self._mem_queue:
            return self._mem_queue.pop(0)
        return None


class MemoryKV:
    """内存 KV（Redis 降级），带过期。"""

    def __init__(self):
        self._d: dict[str, tuple[str, float]] = {}

    async def get(self, key: str):
        v = self._d.get(key)
        if v is None:
            return None
        val, exp = v
        if exp and exp < time.time():
            self._d.pop(key, None)
            return None
        return val

    async def set(self, key: str, value: str, ex: Optional[int] = None) -> None:
        self._d[key] = (value, time.time() + ex if ex else 0)

    async def delete(self, key: str) -> None:
        self._d.pop(key, None)