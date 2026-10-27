# -*- coding: utf-8 -*-
"""DataAgent 企业级 API（Litestar + Granian）。

第 1 层完整落地：B端控制台(SPA) + API Gateway + Auth(JWT)/Tenant/RBAC/Quota。
- / 与 /console → B 端控制台 SPA（登录后可用全部管理页）
- /login → JWT 签发（pbkdf2 校验，用户 CRDB+Redis）
- 业务与管理路由全部 JWT + RBAC 域校验；/healthz /readyz /metrics /graphql 公开
- POST /v1/analysis async_=true → 真实队列（Pulsar 优先/Redis 兜底）→ Worker 消费落库
- 审批 resolve → 后台恢复工作流（HITL interrupt/resume 真实闭环）
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import traceback as _tb
from typing import Any, Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "dataagent", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from litestar import Litestar, Request, Response, get, post
from litestar.di import Provide
from litestar.exceptions import HTTPException, PermissionDeniedException
from pydantic import BaseModel, Field

from services.api import admin as ADM
from services.api import auth as AUTH
from services.api.console_spa import SPA
from services.shared.runtime import (
    IdempotencyGuard,
    InfraProvider,
    RateLimiter,
    Settings,
    new_request_context,
)


# ---------------- 请求模型 ----------------
class LoginRequest(BaseModel):
    username: str
    password: str


class AnalysisRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=2000)
    tenant_id: str = Field(default="ten_a")
    user_id: str = Field(default="u1")
    idempotency_key: str = Field(default="")
    async_: bool = Field(default=False)


class TenantUpsert(BaseModel):
    tenant_id: str
    name: str = ""
    plan: str = "standard"
    roles: str = "analyst"
    row_filter: Optional[str] = None
    col_filter: Optional[str] = None
    quota_rps: int = 60
    status: str = "active"


class MetricUpsert(BaseModel):
    name: str
    display_name: str = ""
    formula: str = ""
    aliases: str = ""
    dimension: str = "amount"
    owner: str = "platform"
    status: str = "active"


class RouteUpsert(BaseModel):
    task: str
    primary_model: str
    fallback_models: str = ""
    max_attempts: int = 3
    timeout_s: int = 60
    cost_cap: float = 10
    status: str = "active"


class MemoryWrite(BaseModel):
    key: str
    content: str
    scope: str = "user"
    owner: str = "u1"
    tenant_id: str = "ten_a"


class ResolveRequest(BaseModel):
    decision: str  # approved / rejected


class ReleaseState(BaseModel):
    version: str = "0.2.0"
    canary_pct: int = 0
    kill_switch: bool = False
    regression_gate: dict = {"code": 0.8}
    released_versions: list = ["0.1.0", "0.2.0"]
    history: list = []


class TaskResponse(BaseModel):
    request_id: str
    task_id: str = ""
    status: str = "accepted"
    run_id: str = ""
    detail: str = ""


class AppState:
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or Settings()
        self.infra = InfraProvider(self.settings)
        self.idem = IdempotencyGuard()
        per = float(os.getenv("DATAAGENT_GATEWAY_RPS_PER_TENANT", "60"))
        burst = float(os.getenv("DATAAGENT_GATEWAY_BURST", "200"))
        self.rate = RateLimiter(per_tenant_rps=per, burst=burst)
        self._container: Any = None

    def container(self):
        if self._container is None:
            from dataagent.app.container import DataAgentContainer, default_seed
            self._container = DataAgentContainer(seed_orders=default_seed())
        return self._container


def get_state() -> AppState:
    return init_state()


_SINGLETON: Optional[AppState] = None


def init_state(settings: Optional[Settings] = None) -> AppState:
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = AppState(settings)
    return _SINGLETON


# ---------------- RBAC guard ----------------
def guard_domain(domain: str):
    def _guard(request: Request, *args: Any, **kwargs: Any) -> None:
        user = request.scope.get("user")
        if user is None:
            from litestar.exceptions import NotAuthorizedException
            raise NotAuthorizedException(detail=f"{domain} 需要登录")
        if not user.can(domain):
            raise PermissionDeniedException(detail=f"角色 {user.role} 无 {domain} 权限（RBAC）")
    _guard.__name__ = f"guard_{domain}"
    return _guard


# ---------------- 公共路由 ----------------
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
    except Exception:  # noqa: BLE001
        redis_ok = False
    return {"status": "ready" if redis_ok else "degraded", "redis": redis_ok}


@get("/metrics")
async def metrics() -> Response:
    try:
        from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
        REQ = Counter("dataagent_http_requests_total", "requests")
        REQ.inc()
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
    except Exception:  # noqa: BLE001
        return Response(content=b"metrics_disabled", media_type="text/plain")


@post("/login")
async def login(data: LoginRequest) -> dict:
    dsn = os.getenv("DATAAGENT_DATABASE_URL", "")
    user = await AUTH.login(dsn, data.username, data.password)
    if user is None:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return {"token": AUTH.make_token(user),
            "user": {"username": user.username, "role": user.role,
                     "full_name": user.full_name, "tenant": user.tenant}}


# ---------------- SPA ----------------
@get("/", media_type="text/html")
async def console_root() -> Response:
    return Response(content=SPA, media_type="text/html")


@get("/console", media_type="text/html")
async def console_page() -> Response:
    return Response(content=SPA, media_type="text/html")


# ---------------- 分析（业务） ----------------
@post("/v1/analysis", guards=[guard_domain("analysis")])
async def create_analysis(request: Request, data: AnalysisRequest, app_state: AppState) -> dict:
    ctx = new_request_context(data.tenant_id, data.user_id)
    # 每租户限流（Quota）
    if not app_state.rate.allow(data.tenant_id):
        raise HTTPException(status_code=429, detail="rate_limited")
    if data.idempotency_key and not app_state.idem.try_acquire(
            data.tenant_id, data.user_id, data.idempotency_key):
        raise HTTPException(status_code=409, detail="duplicate_request")
    if data.async_:
        from services.shared import queue as q
        task = {"kind": "analysis", "query": data.query, "tenant_id": data.tenant_id,
                "user_id": data.user_id, "request_id": ctx.request_id}
        q.enqueue(task)
        try:  # 任务表立即可见（queued）；CRDB 尽力 + 必写镜像
            from dataagent.infra.persistence import cockroach as cr
            rec = {**task, "task_id": ctx.request_id, "status": "queued"}
            try:
                await cr.upsert_task(os.getenv("DATAAGENT_DATABASE_URL", ""), rec)
            except Exception:  # noqa: BLE001
                pass
            await cr.mirror_task_to_redis(rec)
        except Exception:  # noqa: BLE001
            pass
        return TaskResponse(request_id=ctx.request_id, task_id=ctx.request_id, status="queued",
                            detail="已入队（Pulsar 优先/Redis 兜底），Worker 异步消费落库").model_dump()
    try:
        result = await asyncio.to_thread(_run_sync, app_state, data)
    except Exception as e:  # noqa: BLE001
        return {"error": "analysis_failed", "message": str(e)}
    return {"request_id": ctx.request_id, "status": "succeeded", "run": result}


def _run_sync(app_state: AppState, data: AnalysisRequest) -> dict:
    from dataagent.contracts.runtime import Run
    c = app_state.container()
    try:
        run: Run = c.analyze(data.query, data.tenant_id)
    except Exception as e:  # noqa: BLE001  manual 审批模式：同步路径同样中断为待审批
        name = type(e).__name__
        if "ApprovalPending" in name:
            import asyncio as _aio
            from dataagent.infra.persistence import cockroach as cr
            dsn0 = os.getenv("DATAAGENT_DATABASE_URL", "")
            rec = {"task_id": "pending_sync_" + str(int(time.time())), "kind": "analysis",
                   "tenant_id": data.tenant_id, "user_id": data.user_id,
                   "query": data.query, "status": "waiting_approval"}
            try:
                _aio.run(cr.mirror_task_to_redis(rec))
            except Exception:  # noqa: BLE001
                pass
            return {"run_id": "", "status": "waiting_approval",
                    "steps": [], "events": 0, "detail": "manual 审批模式：请经异步任务+审批中心完成闭环"}
        raise
    dsn = os.getenv("DATAAGENT_DATABASE_URL")
    if dsn:
        from dataagent.infra.persistence import cockroach as cr
        payload = {"task_id": run.run_id, "status": run.status.value, "steps": len(run.steps),
                   "events": len(run.events), "tenant_id": run.tenant_id, "query": run.query}
        for attempt in range(2):
            try:
                import asyncio as _aio
                _aio.run(cr.CockroachRunStore(dsn).save(run))
                _aio.run(cr.mirror_run_to_redis(run.run_id, payload))
                break
            except Exception:  # noqa: BLE001
                import time as _t; _t.sleep(1.5 * (attempt + 1))
        else:
            import asyncio as _aio
            _aio.run(cr.mirror_run_to_redis(run.run_id, payload))
    return {"run_id": run.run_id, "status": run.status.value,
            "steps": [{"name": s.name, "status": s.status.value, "output": s.output} for s in run.steps],
            "events": len(run.events)}


@get("/v1/tasks/{task_id:str}", guards=[guard_domain("tasks")])
async def get_task(task_id: str) -> dict:
    dsn = os.getenv("DATAAGENT_DATABASE_URL")
    from dataagent.infra.persistence import cockroach as cr
    try:
        t = await cr.get_task(dsn, task_id)
        if t:
            return t
    except Exception:  # noqa: BLE001
        pass
    m = await cr.read_task_mirror(task_id)
    if m:
        return m
    # 兼容旧同步 run_id
    try:
        rs = cr.CockroachRunStore(dsn)
        run = await rs.load(task_id)
        return {"task_id": run.run_id, "status": run.status.value,
                "steps": len(run.steps), "events": len(run.events)}
    except Exception:  # noqa: BLE001
        m2 = await cr.read_run_mirror(task_id)
        if m2:
            return m2
        raise HTTPException(status_code=404, detail="task not found")


# ---------------- 概览 ----------------
@get("/v1/admin/dashboard", guards=[guard_domain("tasks")])
async def dashboard() -> dict:
    return await ADM.dashboard()


# ---------------- 租户管理 ----------------
@get("/v1/admin/tenants", guards=[guard_domain("tenants")])
async def tenants_list() -> list:
    return await ADM.tenants_list()


@post("/v1/admin/tenants", guards=[guard_domain("tenants")])
async def tenants_upsert(data: TenantUpsert) -> dict:
    return await ADM.tenant_upsert(data.model_dump())


# ---------------- 指标注册中心 ----------------
@get("/v1/admin/metrics", guards=[guard_domain("metrics")])
async def metrics_list() -> list:
    return await ADM.metrics_list()


@post("/v1/admin/metrics", guards=[guard_domain("metrics")])
async def metric_upsert(data: MetricUpsert) -> dict:
    return await ADM.metric_upsert(data.model_dump())


# ---------------- 模型路由 ----------------
@get("/v1/admin/routes", guards=[guard_domain("routing")])
async def routes_list() -> list:
    return await ADM.routes_list()


@post("/v1/admin/routes", guards=[guard_domain("routing")])
async def route_upsert(data: RouteUpsert) -> dict:
    return await ADM.route_upsert(data.model_dump())


# ---------------- Capability 权限矩阵 ----------------
@get("/v1/admin/capability", guards=[guard_domain("capability")])
async def capability() -> dict:
    return ADM.capability_matrix()


# ---------------- Memory 管理 ----------------
@get("/v1/admin/memory", guards=[guard_domain("memory")])
async def memory_list(limit: int = 50, tenant_id: str = "ten_a") -> list:
    return await ADM.memory_list(tenant_id, limit)


@post("/v1/admin/memory", guards=[guard_domain("memory")])
async def memory_write(data: MemoryWrite) -> dict:
    return await ADM.memory_write(data.model_dump())


@post("/v1/admin/memory/{memory_id:str}/delete", guards=[guard_domain("memory")])
async def memory_delete(memory_id: str, tenant_id: str = "ten_a") -> dict:
    ok = await ADM.memory_delete(memory_id, tenant_id)
    return {"deleted": ok}


# ---------------- 审批中心（真实 HITL） ----------------
@get("/v1/admin/approvals", guards=[guard_domain("approvals")])
async def approvals_list(status: str = "pending") -> list:
    return await ADM.approvals_list(status)


@get("/v1/admin/approvals/{approval_id:str}", guards=[guard_domain("approvals")])
async def approval_get(approval_id: str) -> dict:
    a = await ADM.approval_get(approval_id)
    if not a:
        raise HTTPException(status_code=404, detail="approval not found")
    return a


@post("/v1/admin/approvals/{approval_id:str}/resolve", guards=[guard_domain("approvals")])
async def approval_resolve(approval_id: str, data: ResolveRequest, request: Request) -> dict:
    if data.decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="decision 必须为 approved/rejected")
    by = getattr(request.user, "username", "unknown")
    a = await ADM.approval_resolve(approval_id, data.decision, by)
    if not a:
        raise HTTPException(status_code=404, detail="审批单不存在或已决议")
    task_status = "resume_pending"
    try:
        from services.worker.main import resume_after_approval
        task_status = await resume_after_approval(a)
    except Exception as e:  # noqa: BLE001
        task_status = f"resume_failed: {str(e)[:80]}"
    return {"approval_id": approval_id, "decision": data.decision, "decided_by": by,
            "task_status": task_status}


# ---------------- 任务中心 ----------------
@get("/v1/admin/tasks", guards=[guard_domain("tasks")])
async def tasks_list(status: str = "", limit: int = 50) -> list:
    return await ADM.tasks_list(status, limit)


# ---------------- 发布与灰度 ----------------
@get("/v1/admin/release", guards=[guard_domain("release")])
async def release_get() -> dict:
    return await ADM.release_state()


@post("/v1/admin/release", guards=[guard_domain("release")])
async def release_save(data: ReleaseState) -> dict:
    st = data.model_dump()
    st.setdefault("history", [])
    return await ADM.release_save(st)


# ---------------- 应用组装 ----------------
def _on_exc(request, exc: Exception):
    try:
        import pathlib as _pl
        (_pl.Path(os.path.expanduser("~/dataagent_api_err.log"))).write_text(_tb.format_exc(), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    from litestar import Response
    return Response(content={"error": "internal_error", "detail": str(exc)}, status_code=500)


# GraphQL（Strawberry ASGI）
_gql_handler = None
try:
    from strawberry.asgi import GraphQL as StrawberryGraphQL
    from services.api.graphql_schema import schema as gql_schema
    from litestar.handlers import asgi as _asgi_handler

    _gql_app = StrawberryGraphQL(gql_schema, graphql_ide="graphiql")

    async def _gql_endpoint(scope: dict, receive: Any, send: Any) -> None:
        await _gql_app(scope, receive, send)

    _gql_handler = _asgi_handler("/graphql", is_mount=True)(_gql_endpoint)
except Exception:  # noqa: BLE001
    _gql_handler = None


PUBLIC = [r"^/$", r"^/console$", r"^/login$", r"^/healthz$", r"^/readyz$", r"^/metrics$", r"^/graphql$"]

_handlers = [console_root, console_page, login, healthz, readyz, metrics,
             create_analysis, get_task,
             dashboard,
             tenants_list, tenants_upsert,
             metrics_list, metric_upsert,
             routes_list, route_upsert,
             capability,
             memory_list, memory_write, memory_delete,
             approvals_list, approval_get, approval_resolve,
             tasks_list,
             release_get, release_save]
if _gql_handler is not None:
    _handlers.append(_gql_handler)

jwt_auth = AUTH.build_jwt_auth(exclude_paths=PUBLIC)

app = Litestar(
    route_handlers=_handlers,
    dependencies={"app_state": Provide(get_state, sync_to_thread=False)},
    exception_handlers={500: _on_exc},
    middleware=[jwt_auth.middleware],
    openapi_config=None,
)

# 启动引导（尽力而为：用户表/租户/指标/路由表+种子）
try:
    AUTH.try_bootstrap_users()
    ADM.try_bootstrap()
except Exception:  # noqa: BLE001
    pass