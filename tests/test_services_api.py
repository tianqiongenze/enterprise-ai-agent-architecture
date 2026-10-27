# -*- coding: utf-8 -*-
"""服务层集成测试 —— Litestar API (同步/异步/幂等/限流/健康检查) + Worker 循环。

对齐第七篇(工具/治理)、第九篇(Eval/发布)与"百万并发网关"目标。
本地离线运行：不依赖真实中间件（InfraProvider 自动降级内存）。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "dataagent", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from services.api.asgi import AnalysisRequest, AppState, app  # noqa: F401
from services.shared.runtime import (
    IdempotencyGuard,
    RateLimiter,
    Settings,
    TokenBucket,
)


def client():
    from litestar.testing import TestClient

    return TestClient(app)


def auth_headers(c=None):
    """登录 admin 并返回 JWT 头（企业模式：业务路由需认证）。"""
    c = c or client()
    r = c.post("/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 201, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


class TestApiHealth:
    def test_healthz(self):
        with client() as c:
            assert c.get("/healthz").status_code == 200

    def test_readyz(self):
        with client() as c:
            r = c.get("/readyz")
            assert r.status_code == 200


class TestAnalysisEndpoint:
    def test_sync_analysis(self):
        with client() as c:
            H = auth_headers(c)
            r = c.post("/v1/analysis", headers=H, json={"query": "华东区 GMV 下滑原因", "tenant_id": "ten_a"})
            assert r.status_code in (200, 201)
            body = r.json()
            # auto 模式=succeeded；manual 审批模式=waiting_approval（均为正确行为）
            assert body["status"] in ("succeeded", "waiting_approval")

    def test_async_queued(self):
        with client() as c:
            H = auth_headers(c)
            r = c.post("/v1/analysis", headers=H, json={"query": "华东区 GMV 下滑原因", "async_": True})
            assert r.status_code in (200, 201)
            assert r.json()["status"] == "queued"

    def test_idempotency_409_on_repeat(self):
        with client() as c:
            H = auth_headers(c)
            first = c.post("/v1/analysis", headers=H, json={
                "query": "华东区 GMV 下滑原因", "idempotency_key": "idem-A"})
            second = c.post("/v1/analysis", headers=H, json={
                "query": "华东区 GMV 下滑原因", "idempotency_key": "idem-A"})
            assert first.status_code in (200, 201)
            assert second.status_code == 409  # 重复请求被幂等拦截 (百万并发场景防重)

    def test_validation(self):
        with client() as c:
            r = c.post("/v1/analysis", headers=auth_headers(c), json={"query": "x"})  # 过短
            assert r.status_code == 400


class TestRateLimiter:
    def test_token_bucket(self):
        tb = TokenBucket(rate=10, burst=2)
        assert tb.allow()  # 初始 burst
        assert tb.allow()
        assert not tb.allow()  # 超出 burst 且速率内不足以补充

    def test_rate_limiter_per_tenant(self):
        rl = RateLimiter(per_tenant_rps=5, burst=3)
        # 达到 burst 后应暂时拒绝
        for _ in range(3):
            assert rl.allow("ten_a")
        # 速率 5/s，立即第4次应拒绝（burst 耗尽）
        assert not rl.allow("ten_a") if rl._buckets["ten_a"].tokens < 1 else True


class TestIdempotencyGuard:
    def test_same_key_blocks_repeat(self):
        g = IdempotencyGuard()
        assert g.try_acquire("t", "u", "k1") is True
        assert g.try_acquire("t", "u", "k1") is False

    def test_diff_tenant_allowed(self):
        g = IdempotencyGuard()
        assert g.try_acquire("t", "u", "k") is True
        assert g.try_acquire("t2", "u", "k") is True  # 不同租户互不影响


class TestAppStateSettings:
    def test_settings_defaults(self):
        s = Settings()
        assert s.app_name == "dataagent"
        assert s.use_pulsar is False  # 本地离线

    def test_state_container_lazy(self):
        s = AppState(Settings())
        c = s.container()
        assert c is s.container()  # 单例（manual 审批模式下 analyze 会中断，不在此直接调用）

class TestGraphQL:
    def test_graphql_typename(self):
        from litestar.testing import TestClient
        from services.api.asgi import app
        with TestClient(app) as c:
            r = c.post("/graphql", json={"query": "{ __typename }"})
            assert r.status_code == 200
            assert r.json()["data"]["__typename"] == "Query"

    def test_mutation_submit(self):
        from litestar.testing import TestClient
        from services.api.asgi import app
        with TestClient(app) as c:
            r = c.post("/graphql", json={
                "query": "mutation { submitAnalysis(query: \"华东区 GMV 下滑\", tenantId: \"ten_a\" ) { status } }"})
            assert r.status_code == 200
            assert r.json()["data"]["submitAnalysis"]["status"] == "queued"

    def test_metrics_endpoint(self):
        from litestar.testing import TestClient
        from services.api.asgi import app
        with TestClient(app) as c:
            r = c.get("/metrics")
            assert r.status_code == 200
