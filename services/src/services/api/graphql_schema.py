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
        # 1) 优先读预聚合汇总表（毫秒级短事务，规避共享 CRDB 许可并发闸门）
        # 2) CRDB 不可用（闸门饱和/超时）→ Redis 镜像兜底
        # 3) 两者皆无 → 后台调度一次刷新，返回友好错误
        import asyncio as _aio
        from dataagent.infra.persistence import cockroach as cr
        sem = _region_semaphore()
        try:
            async with sem:
                rows = await _aio.wait_for(cr.read_region_summary(dsn, tenant_id, limit), timeout=8)
        except Exception:
            rows = await cr.read_summary_mirror()
        if rows is None:
            _aio.get_running_loop().create_task(_refresh_summary_bg(dsn))
            raise Exception("经营聚合暂不可用：共享 CockroachDB 免费许可的并发事务上限已被其他负载占满，"
                            "已触发后台刷新（汇总表/Redis 镜像就绪后自动恢复），请几分钟后重试。")
        if rows:
            _aio.get_running_loop().create_task(cr.mirror_summary_to_redis(rows))
        return [MetricAggregate(region=r["region"], orders=r["orders"], gmv=r["gmv"]) for r in rows]


_SEM = None


def _region_semaphore():
    """每进程最多 1 个重查询并发（闸门友好）。"""
    global _SEM
    if _SEM is None:
        _SEM = asyncio.Semaphore(1)
    return _SEM


async def _refresh_summary_bg(dsn: str):
    """后台尽力刷新汇总表（失败静默，由引导 Job 重试）。"""
    from dataagent.infra.persistence import cockroach as cr
    try:
        rows = await cr.read_region_summary(dsn, tenant_id="ten_1", limit=1)  # 探针：可读说明已建表
        if rows is not None:
            return  # 表已就绪
    except Exception:
        pass
    try:
        await cr.ensure_summary_table(dsn)
        await cr.refresh_region_summary(dsn)
    except Exception:  # noqa: BLE001  闸门饱和/超时——交由后台 Job 重试
        pass


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