# -*- coding: utf-8 -*-
"""Litestar 应用工厂 + 路由 —— 企业级 API 入口 (多端：Web/移动/内部 Worker)。

- Litestar（全异步）提供路由、校验、依赖注入、OpenAPI。
- Granian 作为 RSGI 运行时（生产），本模块可被 `granian services.api.asgi:app` 加载，
  也可在本地由普通 ASGI 服务器（uvicorn/hypercorn）用同一 app 对象。
- 端点：
  POST /v1/analysis      同步提交一次经营分析（网关：请求ID/幂等/限流）
  POST /v1/analysis/async 异步入队(Pulsar)并返回 task_id（百万并发友好）
  GET  /v1/tasks/{id}    查询任务状态/Run Timeline
  GET  /healthz           存活
  GET  /readyz            就绪(依赖中间件)
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from typing import Any, Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "dataagent", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from litestar import Litestar, get, post
from litestar.di import Provide

from litestar.handlers import get as _get, post as _post
from litestar.exceptions import HTTPException
import traceback as _tb
from pydantic import BaseModel, Field

from services.shared.runtime import (
    InfraProvider,
    IdempotencyGuard,
    RateLimiter,
    RequestContext,
    Settings,
    new_request_context,
)


# ---------------- 请求/响应模型 ----------------
class AnalysisRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=2000, description="经营分析问题")
    tenant_id: str = Field(default="ten_a")
    user_id: str = Field(default="u1")
    idempotency_key: str = Field(default="")
    async_: bool = Field(default=False, description="是否异步入队")


class TaskResponse(BaseModel):
    request_id: str
    task_id: str = ""
    status: str = "accepted"
    run_id: str = ""
    detail: str = ""


# ---------------- 依赖容器（应用单例） ----------------
class AppState:
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or Settings()
        self.infra = InfraProvider(self.settings)
        self.idem = IdempotencyGuard()
        # 每租户 RPS：默认 60，可由环境覆盖（生产按租户/套餐差异配置）
        per_tenant_rps = float(os.getenv("DATAAGENT_GATEWAY_RPS_PER_TENANT", "60"))
        burst = float(os.getenv("DATAAGENT_GATEWAY_BURST", "200"))
        self.rate = RateLimiter(per_tenant_rps=per_tenant_rps, burst=burst)
        self._container: Any = None

    def container(self):
        # 懒加载 DataAgent 内核容器（离线也可用）
        if self._container is None:
            try:
                from dataagent.app.container import DataAgentContainer, default_seed
                self._container = DataAgentContainer(seed_orders=default_seed())
            except Exception as e:  # pragma: no cover
                self._container = {"error": str(e)}
        return self._container


# 单例状态：保证限流/幂等在同一进程内共享（多副本间由 Redis 承担）
_SINGLETON: Optional[AppState] = None


async def init_state(settings: Optional[Settings] = None) -> AppState:
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = AppState(settings)
    return _SINGLETON


async def get_state() -> AppState:
    return await init_state()


# ---------------- 处理器 ----------------
@get("/healthz")
async def healthz() -> dict[str, object]:
    return {"status": "alive", "ts": time.time()}


@get("/readyz")
async def readyz(app_state: AppState) -> dict[str, object]:
    redis_ok = True
    try:
        cache = await app_state.infra.get_cache()
        if hasattr(cache, "ping"):
            await cache.ping()
    except Exception:  # pragma: no cover
        redis_ok = False
    return {"status": "ready" if redis_ok else "degraded", "redis": redis_ok}


@post("/v1/analysis")
async def create_analysis(
    data: AnalysisRequest,
    app_state: AppState,
) -> dict[str, object]:
    from litestar import status_codes
    from litestar.exceptions import HTTPException

    ctx = new_request_context(data.tenant_id, data.user_id)
    # 限流
    if not app_state.rate.allow(data.tenant_id):
        raise HTTPException(status_code=429, detail="rate_limited")
    # 幂等
    if data.idempotency_key:
        if not app_state.idem.try_acquire(data.tenant_id, data.user_id, data.idempotency_key):
            raise HTTPException(status_code=409, detail="duplicate_request")

    if data.async_:
        # 异步入队(Pulsar) —— 百万并发友好
        await app_state.infra.publish(app_state.settings.pulsar_topic, {
            "kind": "analysis",
            "query": data.query,
            "tenant_id": data.tenant_id,
            "user_id": data.user_id,
            "request_id": ctx.request_id,
        })
        return TaskResponse(
            request_id=ctx.request_id, task_id=ctx.request_id, status="queued",
            detail="已入队(Pulsar)，由 Worker 异步执行",
        ).model_dump()

    # 同步：直接调用内核（离线可演示）；失败写盘以便诊断
    try:
        result = await asyncio.to_thread(_run_sync, app_state, data)
    except Exception as e:  # noqa: BLE001
        try:
            import pathlib as _pl
            (_pl.Path(os.path.expanduser("~/dataagent_api_err.log"))).write_text(_tb.format_exc(), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        return {"error": "analysis_failed", "message": str(e)}
    return {"request_id": ctx.request_id, "status": "succeeded", "run": result}


def _run_sync(app_state: AppState, data: AnalysisRequest) -> dict:
    from dataagent.contracts.runtime import Run
    c = app_state.container()
    run: Run = c.analyze(data.query, data.tenant_id)
    return {
        "run_id": run.run_id,
        "status": run.status.value,
        "steps": [{"name": s.name, "status": s.status.value, "output": s.output} for s in run.steps],
        "events": len(run.events),
    }


# ---------------- 读写分离：REST(读/写) + GraphQL(Query 读 / Mutation 写) ----------------
@get("/v1/tasks/{task_id:str}")
async def get_task(task_id: str, app_state: AppState) -> dict[str, object]:
    # 读侧：从 CRDB(可只读副本) 读任务，避免写侧耦合
    from litestar.exceptions import HTTPException
    dsn = os.getenv("DATAAGENT_DATABASE_URL")
    if not dsn:
        raise HTTPException(status_code=404, detail="no datastore configured")
    from dataagent.infra.persistence.cockroach import CockroachRunStore
    rs = CockroachRunStore(dsn)
    try:
        run = await rs.load(task_id)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=404, detail="task not found")
    return {"task_id": run.run_id, "status": run.status.value,
            "steps": len(run.steps), "events": len(run.events)}


@get("/metrics")
async def metrics() -> dict[str, object]:
    """Prometheus 指标端点（进程级）。"""
    try:
        from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
        REQ = Counter("dataagent_http_requests_total", "requests")
        REQ.inc()
        from litestar import Response
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
    except Exception:  # noqa: BLE001
        return {"error": "metrics_disabled"}


# ---------------- 应用 ----------------
def _on_exc(request, exc: Exception):
    import pathlib as _pl
    try:
        (_pl.Path(os.path.expanduser("~/dataagent_api_err.log"))).write_text(_tb.format_exc(), encoding="utf-8")
    except Exception:
        pass
    from litestar import Response
    return Response(content={"error": "internal_error", "detail": str(exc)},
                    status_code=500)


# 挂载 GraphQL（读写分离）：Strawberry 是标准 ASGI 应用，作为 handler 传入 Litestar 构造
_gql_handler = None
try:
    from strawberry.asgi import GraphQL as StrawberryGraphQL
    from services.api.graphql_schema import schema as gql_schema
    from litestar.handlers import asgi as _asgi_handler

    _gql_app = StrawberryGraphQL(gql_schema, graphql_ide="graphiql")

    async def _gql_endpoint(scope: dict, receive: Any, send: Any) -> None:
        await _gql_app(scope, receive, send)

    _gql_handler = _asgi_handler("/graphql", is_mount=True)(_gql_endpoint)
except Exception as _e:  # noqa: BLE001   (未安装 strawberry 时跳过)
    _gql_handler = None


def _with_graphql(routes):
    if _gql_handler is not None:
        return [*routes, _gql_handler]
    return routes


def _with_graphql(routes):
    if _gql_handler is not None:
        return [*routes, _gql_handler]
    return routes


app = Litestar(
    route_handlers=_with_graphql([healthz, readyz, create_analysis, get_task, metrics]),
    dependencies={"app_state": Provide(get_state)},
    exception_handlers={500: _on_exc},
    openapi_config=None,
)