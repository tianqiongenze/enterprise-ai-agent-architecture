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

from litestar import Litestar, Response, get, post
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
    # 配置了 CRDB 时同步落库 → 使 GET /v1/tasks/{run_id} 与 GraphQL task(runId) 人工可查
    dsn = os.getenv("DATAAGENT_DATABASE_URL")
    if dsn:
        try:
            import asyncio as _aio
            from dataagent.infra.persistence.cockroach import CockroachRunStore
            _aio.run(CockroachRunStore(dsn).save(run))
        except Exception:  # noqa: BLE001  落库失败不影响分析结果返回
            pass
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


CONSOLE_HTML = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DataAgent 人工测试控制台</title>
<style>
:root{--p:#0e7490;--pd:#0a5568;--acc:#06b6d4;--bg:#f5f7fa;--ink:#1f2937;--mut:#6b7280;--ok:#059669;--err:#dc2626;--warn:#d97706}
*{box-sizing:border-box;margin:0}
body{font-family:"Microsoft YaHei",system-ui,sans-serif;background:var(--bg);color:var(--ink);padding:18px}
header{background:var(--p);color:#fff;padding:14px 18px;border-radius:10px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px}
header h1{font-size:18px} header .u{font-size:12px;opacity:.9}
main{max-width:1180px;margin:16px auto;display:grid;grid-template-columns:1fr 1fr;gap:14px}
.card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.card h2{font-size:14px;color:var(--pd);margin-bottom:10px;border-left:4px solid var(--acc);padding-left:8px}
label{font-size:12px;color:var(--mut);display:block;margin:6px 0 3px}
input,select,textarea{width:100%;padding:7px 9px;border:1px solid #d1d5db;border-radius:6px;font-size:13px;font-family:inherit}
textarea{min-height:64px;resize:vertical}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:end}
.row>*{flex:1;min-width:120px}
button{background:var(--p);color:#fff;border:0;border-radius:6px;padding:8px 14px;font-size:13px;cursor:pointer;margin-top:8px}
button:hover{background:var(--pd)} button.ghost{background:#fff;color:var(--p);border:1px solid var(--p)}
pre{background:#0f172a;color:#abb2bf;padding:10px;border-radius:8px;font-size:12px;max-height:260px;overflow:auto;white-space:pre-wrap;font-family:Consolas,monospace}
.tag{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;margin-left:6px}
.ok{background:#d1fae5;color:var(--ok)} .err{background:#fee2e2;color:var(--err)} .warn{background:#fef3c7;color:var(--warn)}
.hint{font-size:12px;color:var(--mut);margin-top:8px;line-height:1.6}
.full{grid-column:1/-1}
</style></head><body>
<header><h1>DataAgent 人工测试控制台</h1>
<div class="u">Base: <input id="base" style="width:260px;padding:3px 6px;border:0;border-radius:4px" value="">
<a href="/graphql" target="_blank" style="color:#a5f3fc;margin-left:10px">GraphiQL ↗</a>
<a href="/metrics" target="_blank" style="color:#a5f3fc;margin-left:8px">Metrics ↗</a></div></header>
<main>
<div class="card"><h2>① 健康检查</h2>
<div class="row"><button onclick="get('/healthz','o1')">GET /healthz</button>
<button onclick="get('/readyz','o1')">GET /readyz</button></div>
<pre id="o1">点击按钮检测存活/就绪</pre>
<div class="hint">预期：healthz → <b>{"status":"alive"}</b>；readyz → <b>{"status":"ready"}</b>。任意节点 IP 皆可（175/176）。</div></div>

<div class="card"><h2>② 提交经营分析</h2>
<label>租户 tenant_id</label><select id="tenant"><option>ten_a</option><option>ten_b</option><option>ten_c</option></select>
<label>用户 user_id</label><input id="user" value="u1">
<label>分析问题 query</label><input id="q" value="华东区本月 GMV 下滑原因诊断">
<label>幂等键 idempotency_key（重复提交应 409）</label>
<div class="row"><input id="idem" placeholder="留空=不启用幂等"><button class="ghost" style="flex:0" onclick="idem.value='idem-'+Date.now()">生成</button></div>
<div class="row"><button onclick="submit(false)">同步分析</button><button onclick="submit(true)">异步入队</button></div>
<pre id="o2">同步=等结果（可复制 run_id）；异步=入队（内存队列演示模式）</pre>
<div class="hint">预期：HTTP <b>201</b> + run.steps 含 plan/query/analyze/conclusion。相同幂等键再点 → <b>409 duplicate_request</b>。</div></div>

<div class="card"><h2>③ 任务查询（用②返回的 run_id）</h2>
<div class="row"><input id="rid" placeholder="run_xxxxxxxxxx"><button onclick="get('/v1/tasks/'+rid.value.trim(),'o3')">GET /v1/tasks/{run_id}</button></div>
<pre id="o3">先在②同步执行一次，复制 run_id 到这里查询（结果已落 CockroachDB）</pre>
<div class="hint">预期：200 + {"status":"succeeded","steps":7,...}；乱填 ID → <b>404</b>。</div></div>

<div class="card"><h2>④ GraphQL（读写分离验证）</h2>
<label>查询（Query=读 CRDB）</label>
<textarea id="gq">{ regionMetrics(tenantId: "ten_1", limit: 3) { region orders gmv } }</textarea>
<div class="row"><button onclick="gql()">执行 Query</button>
<button class="ghost" onclick="gq.value='{ __typename }'">preset: typename</button>
<button class="ghost" onclick="gq.value='mutation { submitAnalysis(query: \\"华东区 GMV 下滑\\", tenantId: \\"ten_a\\") { status } }'">preset: mutation</button></div>
<pre id="o4">POST /graphql —— 从 ≥1 亿行 orders 表聚合</pre>
<div class="hint">预期 regionMetrics 返回真实聚合（华东/华北…）。大表聚合首次可能 10s+，属正常。</div></div>

<div class="card full"><h2>请求日志</h2><pre id="log" style="max-height:200px">（空）</pre></div>
</main>
<script>
const B=document.getElementById('base');B.value=location.origin;
function log(m){const L=document.getElementById('log');L.textContent=`[${new Date().toLocaleTimeString()}] ${m}\\n`+L.textContent}
async function call(path, opt){const t0=performance.now();try{const r=await fetch(B.value+path,opt);const j=await r.text();const ms=(performance.now()-t0).toFixed(0);log(`${opt?.method||'GET'} ${path} → ${r.status} (${ms}ms)`);return {code:r.status,body:j,ms}}catch(e){log(`${path} → NET-ERR ${e}`);return {code:0,body:'网络错误：'+e,ms:0}}}
function show(id,res){document.getElementById(id).textContent=`HTTP ${res.code} (${res.ms}ms)\\n`+(res.code===0?res.body:(()=>{try{return JSON.stringify(JSON.parse(res.body),null,2)}catch(e){return res.body}})());
 const el=document.getElementById(id);el.classList.remove('ok','err','warn');el.classList.add(res.code>=200&&res.code<300?'ok':res.code===429||res.code===409?'warn':'err')}
async function get(p,o){show(o,await call(p))}
async function submit(a){const body={query:document.getElementById('q').value,tenant_id:document.getElementById('tenant').value,user_id:document.getElementById('user').value,async_:a};
 const ik=document.getElementById('idem').value.trim();if(ik)body.idempotency_key=ik;
 const res=await call('/v1/analysis',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});show('o2',res);
 try{const j=JSON.parse(res.body);if(j.run&&j.run.run_id)document.getElementById('rid').value=j.run.run_id}catch(e){}}
async function gql(){const res=await call('/graphql',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:document.getElementById('gq').value})});show('o4',res)}
</script></body></html>"""


@get("/", media_type="text/html")
async def console_root() -> Response:
    return Response(content=CONSOLE_HTML, media_type="text/html")


@get("/console", media_type="text/html")
async def console_page() -> Response:
    return Response(content=CONSOLE_HTML, media_type="text/html")


def _with_graphql(routes):
    if _gql_handler is not None:
        return [*routes, _gql_handler]
    return routes


app = Litestar(
    route_handlers=_with_graphql([console_root, console_page, healthz, readyz, create_analysis, get_task, metrics]),
    dependencies={"app_state": Provide(get_state)},
    exception_handlers={500: _on_exc},
    openapi_config=None,
)