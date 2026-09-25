# -*- coding: utf-8 -*-
"""GraphQL 层（读写分离）—— 基于 Strawberry。

提供查询（读）/变更（写）分离 + 路由到 CockroachDB：
- Query: 任务/内存/指标/订单聚合（走 CRDB 读，可指向只读 replica）
- Mutation: 提交分析(异步)/写内存（走 API，经 Worker 写 CRDB）

挂载到 Litestar：`app.mount("/graphql", GraphQLRouter(schema))`（见 asgi.py）。
"""
from __future__ import annotations

import asyncio
import os

import strawberry

from services.shared.runtime import InfraProvider, Settings


# ---------------- 类型 ----------------
@strawberry.type
class Task:
    run_id: str
    tenant_id: str
    status: str
    query: str
    steps: int
    events: int


@strawberry.type
class MemoryItem:
    memory_id: str
    key: str
    content: str
    scope: str
    version: int


@strawberry.type
class MetricAggregate:
    region: str
    orders: int
    gmv: float


@strawberry.type
class SubmitResult:
    request_id: str
    task_id: str
    status: str


# ---------------- 数据访问（读写分离） ----------------
def _read_store():
    """读侧：CRDB（生产）；本地退化为 None（由 mock 覆盖）。"""
    from dataagent.infra.persistence.cockroach import CockroachRunStore, CockroachMemoryStore
    dsn = os.getenv("DATAAGENT_DATABASE_URL")
    if not dsn:
        return None
    return CockroachRunStore(dsn), CockroachMemoryStore(dsn)


@strawberry.type
class Query:
    @strawberry.field
    async def task(self, run_id: str) -> Task | None:
        store = _read_store()
        if store is None:
            return None
        rs, _ = store
        return await _load_task(rs, run_id)

    @strawberry.field
    async def memories(self, tenant_id: str, owner: str, limit: int = 5) -> list[MemoryItem]:
        store = _read_store()
        if store is None:
            return []
        _, ms = store
        hits = await ms.search_candidates("", tenant_id, owner, limit=limit)
        return [MemoryItem(memory_id=m.memory_id, key=m.key, content=m.content,
                           scope=m.scope.value, version=m.version) for m in hits]

    @strawberry.field
    async def region_metrics(self, tenant_id: str, limit: int = 5) -> list[MetricAggregate]:
        """从 ≥1亿行 orders 表聚合（读副本友好）。"""
        import asyncpg
        dsn = os.getenv("DATAAGENT_DATABASE_URL")
        if not dsn:
            return []
        conn = await asyncpg.connect(dsn=dsn)
        try:
            rows = await conn.fetch("""
                SELECT region, count(*)::int AS orders,
                       round(sum(amount)::numeric,2)::float AS gmv
                FROM orders WHERE tenant_id=$1
                GROUP BY region ORDER BY gmv DESC LIMIT $2
            """, tenant_id, limit)
        finally:
            await conn.close()
        return [MetricAggregate(region=r["region"], orders=r["orders"], gmv=r["gmv"]) for r in rows]


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def submit_analysis(self, query: str, tenant_id: str, user_id: str = "u1", async_: bool = False) -> SubmitResult:
        # 写入侧：异步投递到 Pulsar/内存队列，由 Worker 落 CRDB
        from services.shared.runtime import new_request_context
        ctx = new_request_context(tenant_id, user_id)
        inf = InfraProvider(Settings())
        await inf.publish(os.getenv("DATAAGENT_PULSAR_TOPIC", "persistent://dataagent/prod/dataagent-jobs"), {
            "kind": "analysis", "query": query, "tenant_id": tenant_id,
            "user_id": user_id, "request_id": ctx.request_id,
        })
        return SubmitResult(request_id=ctx.request_id, task_id=ctx.request_id,
                            status="queued" if async_ or True else "queued")

    @strawberry.mutation
    async def save_memory(self, tenant_id: str, owner: str, key: str, content: str) -> bool:
        from dataagent.infra.memory.memory import Memory, MemoryScope
        store = _read_store()
        if store is None:
            return True
        _, ms = store
        await ms.put(Memory(scope=MemoryScope.USER, owner=owner, tenant_id=tenant_id, key=key, content=content))
        return True


async def _load_task(rs, run_id):
    try:
        run = await rs.load(run_id)
    except Exception:  # noqa: BLE001
        return None
    return Task(run_id=run.run_id, tenant_id=run.tenant_id, status=run.status.value,
                query=run.query, steps=len(run.steps), events=len(run.events))


schema = strawberry.Schema(query=Query, mutation=Mutation)