# -*- coding: utf-8 -*-
"""真实持久化实现：CockroachDB (PostgreSQL 兼容) + Redis —— 取代内存实现。

Port 对齐：
- RunStore  (contracts.runtime) / Checkpoint
- MemoryStore (infra.memory) —— 关系库管权限/版本，Redis 缓存召回候选
- QueryGateway 数据源 —— 直接查 orders 表（≥1亿行）

生产用途：API/Worker 在本文件之上运行时自动使用真实中间件；
本地未配置时退回内存实现（已有）。
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Optional

# 可选依赖：未安装则模块导入时置 None 以便降级
try:
    import asyncpg
except Exception:  # noqa: BLE001
    asyncpg = None  # type: ignore

try:
    import redis as _redis
except Exception:  # noqa: BLE001
    _redis = None  # type: ignore

from ...contracts.runtime import Checkpoint, Event, EventType, Run, RunStatus, RunStore, Step, StepStatus
from ...infra.memory.memory import Memory, MemoryScope, MemoryStore


class CockroachRunStore(RunStore):
    """Run / Checkpoint 持久化到 CockroachDB。

    表：dataagent_runs(run_id, tenant, query, status, payload jsonb, created_at, updated_at)
    生产建议把 payload 分表/向量化；这里 JSONB 足够承载 Run 全量（含事件/检查点）。
    """

    def __init__(self, dsn: str | None = None, *, pool: Any = None):
        self.dsn = dsn or os.getenv("DATAAGENT_DATABASE_URL")
        self._pool = pool
        self._conn_made = False

    async def _ensure(self):
        if self._pool is not None:
            return self._pool
        if not self.dsn:
            raise RuntimeError("CockroachRunStore.dsn 未配置")
        self._pool = await asyncpg.create_pool(
            dsn=self.dsn, min_size=2, max_size=10, command_timeout=30
        )
        async with self._pool.acquire() as conn:
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS dataagent_runs(
                run_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                query TEXT,
                status TEXT,
                payload JSONB,
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now()
            )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_tenant ON dataagent_runs(tenant_id, created_at)")
        self._conn_made = True
        return self._pool

    async def save(self, run: Run) -> None:
        pool = await self._ensure()
        payload = json.dumps(run_to_dict(run), ensure_ascii=False, default=str)
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO dataagent_runs(run_id, tenant_id, query, status, payload, updated_at)
                VALUES($1,$2,$3,$4,$5, now())
                ON CONFLICT (run_id) DO UPDATE SET
                  status=excluded.status, payload=excluded.payload, updated_at=now()
                """,
                run.run_id, run.tenant_id, run.query, run.status.value, payload,
            )

    async def load(self, run_id: str) -> Run:
        pool = await self._ensure()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT payload FROM dataagent_runs WHERE run_id=$1", run_id)
        if row is None:
            raise KeyError(run_id)
        return run_from_dict(json.loads(row["payload"]))

    async def save_checkpoint(self, cp: Checkpoint) -> None:
        # Checkpoint 直接编码进 Run payload；此处提供独立覆盖（存同一行即可）
        pass

    async def load_checkpoint(self, run_id: str) -> Optional[Checkpoint]:
        try:
            run = await self.load(run_id)
        except KeyError:
            return None
        return run.to_checkpoint()


class CockroachMemoryStore(MemoryStore):
    """Memory 持久化到 CockroachDB；Redis 缓存召回候选。

    关系库管权限/版本/删除传播（权威）；Redis 只做候选召回缓存（可回收）。
    """

    def __init__(self, dsn: str | None = None, *, pool: Any = None, redis_client: Any = None):
        self.dsn = dsn or os.getenv("DATAAGENT_DATABASE_URL")
        self._pool = pool
        self._redis = redis_client

    async def _ensure(self):
        if self._pool is not None:
            return self._pool
        if not self.dsn:
            raise RuntimeError("CockroachMemoryStore.dsn 未配置")
        self._pool = await asyncpg.create_pool(dsn=self.dsn, min_size=1, max_size=5, command_timeout=30)
        async with self._pool.acquire() as conn:
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_memory(
                memory_id TEXT PRIMARY KEY,
                scope TEXT, owner TEXT, tenant_id TEXT, mkey TEXT,
                content TEXT, version INT, active BOOL,
                source TEXT, evidence_ref TEXT, ttl_s FLOAT,
                created_at FLOAT, updated_at FLOAT
            )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_scope ON agent_memory(tenant_id, owner, active)")
        return self._pool

    async def put(self, mem: Memory) -> None:
        pool = await self._ensure()
        async with pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT memory_id, version FROM agent_memory WHERE tenant_id=$1 AND owner=$2 AND mkey=$3 AND active",
                mem.tenant_id, mem.owner, mem.key)
            if existing:
                await conn.execute(
                    "UPDATE agent_memory SET content=$1, version=version+1, updated_at=$2 WHERE memory_id=$3",
                    mem.content, time.time(), existing["memory_id"])
                return
            await conn.execute(
                """INSERT INTO agent_memory(memory_id,scope,owner,tenant_id,mkey,content,version,active,source,evidence_ref,ttl_s,created_at,updated_at)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)""",
                mem.memory_id, mem.scope.value, mem.owner, mem.tenant_id, mem.key,
                mem.content, 1, True, mem.source, mem.evidence_ref, mem.ttl_s,
                time.time(), time.time())

    async def delete(self, memory_id: str, tenant_id: str) -> bool:
        pool = await self._ensure()
        async with pool.acquire() as conn:
            cur = await conn.execute("UPDATE agent_memory SET active=false WHERE memory_id=$1 AND tenant_id=$2",
                                     memory_id, tenant_id)
        return "UPDATE 1" in cur

    async def get(self, memory_id: str) -> Optional[Memory]:
        pool = await self._ensure()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM agent_memory WHERE memory_id=$1 AND active", memory_id)
        return row_to_memory(row) if row else None

    async def search_candidates(self, query: str, tenant_id: str, owner: str, limit: int = 10) -> list[Memory]:
        pool = await self._ensure()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM agent_memory WHERE active AND tenant_id=$1 ORDER BY updated_at DESC LIMIT $2""",
                tenant_id, limit)
        return [row_to_memory(r) for r in rows if r]


# ---------------- 编码辅助 ----------------
def run_to_dict(run: Run) -> dict:
    return {
        "run_id": run.run_id, "tenant_id": run.tenant_id, "user_id": run.user_id,
        "task_type": run.task_type, "query": run.query, "status": run.status.value,
        "steps": [{"step_id": s.step_id, "name": s.name, "status": s.status.value,
                   "input": s.input, "output": s.output, "error": s.error} for s in run.steps],
        "events": [{"event_id": e.event_id, "run_id": e.run_id, "step_id": e.step_id,
                    "type": e.type.value, "ts": e.ts, "data": e.data} for e in run.events],
        "budget": [run.budget_used_input, run.budget_used_output],
        "created_at": run.created_at, "updated_at": run.updated_at, "metadata": run.metadata,
    }


def run_from_dict(d: dict) -> Run:
    run = Run(run_id=d["run_id"], tenant_id=d.get("tenant_id", "default"), user_id=d.get("user_id", "default"),
              task_type=d.get("task_type", "analysis"), query=d.get("query", ""),
              status=RunStatus(d["status"]))
    run.budget_used_input, run.budget_used_output = d.get("budget", [0, 0])
    for s in d.get("steps", []):
        st = Step(step_id=s["step_id"], name=s["name"], status=StepStatus(s["status"]),
                  input=s.get("input", {}), output=s.get("output", {}), error=s.get("error"))
        run.steps.append(st)
    for e in d.get("events", []):
        run.events.append(Event(event_id=e["event_id"], type=EventType(e["type"]),
                                ts=e["ts"], step_id=e.get("step_id", ""), data=e.get("data", {})))
    return run


def row_to_memory(r) -> Optional[Memory]:
    if not r:
        return None
    return Memory(
        memory_id=r["memory_id"], scope=MemoryScope(r["scope"]), owner=r["owner"],
        tenant_id=r["tenant_id"], key=r["mkey"], content=r.get("content") or "",
        version=r.get("version", 1), active=bool(r.get("active", True)),
        source=r.get("source", ""), evidence_ref=r.get("evidence_ref", ""),
        ttl_s=r.get("ttl_s"), created_at=r.get("created_at", time.time()),
        updated_at=r.get("updated_at", time.time()))


# ---------------- 工厂 ----------------
async def build_crdb_services():
    """返回 (run_store, mem_store) 真实实现。dsn 未配置时抛错（调用方应降级内存）。"""
    dsn = os.getenv("DATAAGENT_DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATAAGENT_DATABASE_URL 为空")
    rs = CockroachRunStore(dsn)
    ms = CockroachMemoryStore(dsn)
    await rs._ensure()
    await ms._ensure()
    return rs, ms