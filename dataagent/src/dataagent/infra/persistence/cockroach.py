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
import re
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

# ================= 许可闸门韧性层（第三轮新增） =================
# 共享 CockroachDB 免费许可有"并发打开事务 ≤10"的集群级上限；被其他负载占满时
# 任何查询（含 SELECT 1）都会被立即拒绝。以下机制把热路径对 CRDB 的同步依赖降到最低：
#   1) regionMetrics 读预聚合汇总表（毫秒级短事务）+ Redis 镜像兜底
#   2) Run 状态：CRDB 主写 + Redis 镜像；读取失败回退 Redis
#   3) 所有连接带 statement_timeout 与 application_name，防自身慢查询占坑
#   4) 引导/刷新脚本 scripts/refresh_region_summary.py 带"无限重试+退避"

APP_NAME = "dataagent"
LICENSE_GATE_HINT = "CRDB 免费许可并发事务上限已饱和（共享集群其他负载占用）"


def _conn_kwargs(host: str, port: int, user: str, database: str, password: str,
                 timeout_s: int) -> dict:
    return dict(host=host, port=port, user=user, database=database, password=password,
                timeout=timeout_s,
                server_settings={"application_name": APP_NAME,
                                 "statement_timeout": str(timeout_s * 1000)})


def _dsn_kwargs(dsn: str, timeout_s: int) -> dict:
    """从 postgresql://user@host:port/db?sslmode=... 解析；附加 server_settings。"""
    from urllib.parse import urlparse, unquote
    u = urlparse(dsn)
    kw = dict(user=unquote(u.username or "root"), timeout=timeout_s,
              server_settings={"application_name": APP_NAME,
                               "statement_timeout": str(timeout_s * 1000)})
    if u.password:
        kw["password"] = unquote(u.password)
    if u.port:
        kw["port"] = u.port
    db = (u.path or "/defaultdb").lstrip("/")
    kw["database"] = db
    # host 可能含多个逗号分隔值
    kw["host"] = u.hostname or "localhost"
    return kw


async def _connect_kwargs_from_dsn(dsn: str, timeout_s: int = 8):
    return await asyncpg.connect(**_dsn_kwargs(dsn, timeout_s))


_REDIS_CLI_BY_LOOP: dict = {}  # redis.asyncio 客户端绑定事件循环 → 按循环缓存


async def _redis_fallback():
    """返回 (client, enabled)；异步客户端，自动识别集群模式（MOVED 自动跟随）。

    - 单机/主从：redis.Redis
    - 集群（redis8 三节点 30090-30092）：redis.cluster.RedisCluster
    - 连接失败：进程内 dict 兜底（保证演示链路不断）
    """
    import asyncio as _aio2
    loop_id = id(_aio2.get_running_loop())
    cli = _REDIS_CLI_BY_LOOP.get(loop_id)
    url = os.getenv("DATAAGENT_REDIS_FALLBACK", "")
    if not url or _redis is None:
        return _mem_fallback(), True
    if cli is not None:
        return cli, True
    from urllib.parse import urlparse, unquote
    u = urlparse(url)
    host = u.hostname or "127.0.0.1"
    port = u.port or 6379
    pwd = unquote(u.password) if u.password else None
    import redis.asyncio as _redis_ai
    try:
        probe = _redis_ai.Redis(host=host, port=port, password=pwd,
                                decode_responses=True, socket_timeout=3)
        clustered = False
        try:
            clustered = bool((await probe.info("cluster")).get("cluster_enabled"))
        except Exception:  # noqa: BLE001  MOVED 等集群响应 → 按集群处理
            clustered = True
        try:
            await probe.aclose()
        except Exception:  # noqa: BLE001
            pass
        if clustered:
            from redis.asyncio.cluster import RedisCluster
            cli = RedisCluster(host=host, port=port, password=pwd,
                               decode_responses=True,
                               socket_timeout=3, socket_connect_timeout=3)
        else:
            cli = probe
        _REDIS_CLI_BY_LOOP[loop_id] = cli
        return cli, True
    except Exception:  # noqa: BLE001
        return _mem_fallback(), True


_MEM = None


def _mem_fallback():
    global _MEM
    if _MEM is None:
        _MEM = _MemFallback()
    return _MEM


class _MemFallback:
    """进程内 dict 兜底（Redis 完全不可用时保演示链路）。"""

    def __init__(self):
        self.d: dict = {}
        self.exp: dict = {}
        self.sets: dict = {}

    def _clean(self, k):
        import time as _t
        if k in self.exp and self.exp[k] < _t.time():
            self.d.pop(k, None); self.exp.pop(k, None)

    async def get(self, k):
        self._clean(k); return self.d.get(k)

    async def set(self, k, v, ex=None):
        import time as _t
        self.d[k] = v
        if ex: self.exp[k] = _t.time() + ex
        return True

    async def delete(self, k):
        self.d.pop(k, None); self.exp.pop(k, None); return 1

    async def sadd(self, k, v):
        self.sets.setdefault(k, set()).add(v); return 1

    async def srem(self, k, v):
        self.sets.get(k, set()).discard(v); return 1

    async def smembers(self, k):
        return set(self.sets.get(k, set()))

    async def lpush(self, k, v):
        self.d.setdefault(k, []).insert(0, v); return 1

    async def brpop(self, keys, timeout=1):
        import time as _t
        end = _t.time() + timeout
        while _t.time() < end:
            for k in keys:
                lst = self.d.get(k)
                if lst:
                    return (k, lst.pop())
            _t.sleep(0.1)
        return None


RUN_MIRROR_TTL = 7 * 24 * 3600


async def mirror_run_to_redis(run_id: str, payload: dict) -> bool:
    cli, ok = await _redis_fallback()
    if not ok:
        return False
    try:
        await cli.set(f"dataagent:run:{run_id}", json.dumps(payload, ensure_ascii=False),
                      ex=RUN_MIRROR_TTL)
        return True
    except Exception:  # noqa: BLE001
        return False


async def read_run_mirror(run_id: str) -> Optional[dict]:
    cli, ok = await _redis_fallback()
    if not ok:
        return None
    try:
        raw = await cli.get(f"dataagent:run:{run_id}")
        return json.loads(raw) if raw else None
    except Exception:  # noqa: BLE001
        return None


SUMMARY_TABLE = "orders_region_summary"


async def ensure_summary_table(dsn: str) -> None:
    conn = await _connect_kwargs_from_dsn(dsn, timeout_s=15)
    try:
        await conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {SUMMARY_TABLE}(
            tenant_id STRING NOT NULL,
            region STRING NOT NULL,
            orders INT NOT NULL,
            gmv FLOAT NOT NULL,
            refreshed_at TIMESTAMPTZ DEFAULT now(),
            PRIMARY KEY (tenant_id, region)
        )
        """)
    finally:
        await conn.close()


async def refresh_region_summary(dsn: str) -> int:
    """全量聚合 ≥1亿行 orders → 汇总表（重事务；由引导脚本在闸门开启时调用）。"""
    conn = await _connect_kwargs_from_dsn(dsn, timeout_s=900)  # 15 分钟语句超时
    try:
        await conn.execute(f"DELETE FROM {SUMMARY_TABLE}")
        n = await conn.fetchval(f"""
        INSERT INTO {SUMMARY_TABLE}(tenant_id, region, orders, gmv, refreshed_at)
        SELECT tenant_id, region, count(*)::INT, round(sum(amount)::numeric,2)::FLOAT, now()
        FROM orders GROUP BY tenant_id, region
        """)
        cnt = await conn.fetchval(f"SELECT count(*) FROM {SUMMARY_TABLE}")
        return int(cnt or 0)
    finally:
        await conn.close()


async def read_region_summary(dsn: str, tenant_id: str, limit: int) -> Optional[list]:
    """毫秒级读汇总表；闸门饱和抛异常由上层回退 Redis。"""
    conn = await _connect_kwargs_from_dsn(dsn, timeout_s=6)
    try:
        rows = await conn.fetch(
            f"SELECT region, orders, gmv FROM {SUMMARY_TABLE} WHERE tenant_id=$1 "
            f"ORDER BY gmv DESC LIMIT $2", tenant_id, limit)
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def mirror_summary_to_redis(rows: list) -> bool:
    cli, ok = await _redis_fallback()
    if not ok:
        return False
    try:
        await cli.set("dataagent:region_summary", json.dumps(rows, ensure_ascii=False),
                      ex=24 * 3600)
        return True
    except Exception:  # noqa: BLE001
        return False


async def read_summary_mirror() -> Optional[list]:
    cli, ok = await _redis_fallback()
    if not ok:
        return None
    try:
        raw = await cli.get("dataagent:region_summary")
        return json.loads(raw) if raw else None
    except Exception:  # noqa: BLE001
        return None


# ================= 任务与审批存储（真实落库） =================
TASKS_TABLE = "dataagent_tasks"
APPROVALS_TABLE = "dataagent_approvals"


async def ensure_task_tables(dsn: str) -> None:
    conn = await _connect_kwargs_from_dsn(dsn, timeout_s=15)
    try:
        await conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {TASKS_TABLE}(
            task_id TEXT PRIMARY KEY,
            kind STRING NOT NULL,
            tenant_id STRING,
            user_id STRING,
            query STRING,
            status STRING NOT NULL,
            run_id STRING,
            approval_id STRING,
            error STRING,
            updated_at TIMESTAMPTZ DEFAULT now()
        )
        """)
        await conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {APPROVALS_TABLE}(
            approval_id TEXT PRIMARY KEY,
            run_id STRING,
            task_id STRING,
            action STRING NOT NULL,
            params JSONB,
            risk_level STRING,
            status STRING NOT NULL,
            requested_by STRING,
            decided_by STRING,
            decided_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """)
    finally:
        await conn.close()


async def upsert_task(dsn: str, task: dict) -> None:
    conn = await _connect_kwargs_from_dsn(dsn, timeout_s=10)
    try:
        await conn.execute(f"""
        INSERT INTO {TASKS_TABLE}(task_id,kind,tenant_id,user_id,query,status,run_id,approval_id,error,updated_at)
        VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,now())
        ON CONFLICT (task_id) DO UPDATE SET
          status=excluded.status, run_id=COALESCE(excluded.run_id,{TASKS_TABLE}.run_id),
          approval_id=COALESCE(excluded.approval_id,{TASKS_TABLE}.approval_id),
          error=excluded.error, updated_at=now()
        """, task.get("task_id"), task.get("kind", "analysis"), task.get("tenant_id"),
            task.get("user_id"), task.get("query"), task.get("status"),
            task.get("run_id"), task.get("approval_id"), task.get("error"))
    finally:
        await conn.close()


async def get_task(dsn: str, task_id: str) -> Optional[dict]:
    conn = await _connect_kwargs_from_dsn(dsn, timeout_s=6)
    try:
        r = await conn.fetchrow(f"SELECT * FROM {TASKS_TABLE} WHERE task_id=$1", task_id)
        return dict(r) if r else None
    finally:
        await conn.close()


async def mirror_task_to_redis(task: dict) -> bool:
    cli, ok = await _redis_fallback()
    if not ok:
        return False
    try:
        tid = task.get("task_id")
        await cli.set(f"dataagent:task:{tid}",
                      json.dumps(task, ensure_ascii=False, ex=None) if False else json.dumps(task, ensure_ascii=False), ex=RUN_MIRROR_TTL)
        await cli.sadd("dataagent:tasks:all", tid)
        return True
    except Exception:  # noqa: BLE001
        return False


async def list_tasks_mirror(limit: int = 50) -> list:
    """Redis 镜像兜底列表（闸门饱和时）。"""
    cli, ok = await _redis_fallback()
    if not ok:
        return []
    try:
        ids = await cli.smembers("dataagent:tasks:all")
        out = []
        for i in list(ids)[: limit * 3]:
            key = i.decode() if isinstance(i, bytes) else i
            raw = await cli.get(f"dataagent:task:{key}")
            if raw:
                out.append(json.loads(raw))
        out.sort(key=lambda t: str(t.get("updated_at", "")), reverse=True)
        return out[:limit]
    except Exception:  # noqa: BLE001
        return []


async def read_task_mirror(task_id: str) -> Optional[dict]:
    cli, ok = await _redis_fallback()
    if not ok:
        return None
    try:
        raw = await cli.get(f"dataagent:task:{task_id}")
        return json.loads(raw) if raw else None
    except Exception:  # noqa: BLE001
        return None


async def mirror_approval_to_redis(appr: dict) -> bool:
    cli, ok = await _redis_fallback()
    if not ok:
        return False
    try:
        await cli.set(f"dataagent:approval:{appr.get('approval_id')}",
                      json.dumps(appr, ensure_ascii=False), ex=RUN_MIRROR_TTL)
        await cli.sadd("dataagent:approvals:pending", appr.get("approval_id"))
        if appr.get("status") != "pending":
            await cli.srem("dataagent:approvals:pending", appr.get("approval_id"))
        return True
    except Exception:  # noqa: BLE001
        return False


async def create_approval(dsn: str, rec: dict) -> dict:
    import time as _t
    import uuid as _uuid
    rec = dict(rec)
    rec.setdefault("approval_id", f"apr_{_uuid.uuid4().hex[:10]}")
    rec.setdefault("status", "pending")
    rec.setdefault("created_at", _t.time())
    try:
        conn = await _connect_kwargs_from_dsn(dsn, timeout_s=10)
        try:
            await conn.execute(f"""
            INSERT INTO {APPROVALS_TABLE}(approval_id,run_id,task_id,action,params,risk_level,status,requested_by,created_at)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,now())
            """, rec.get("approval_id"), rec.get("run_id"), rec.get("task_id"),
                rec.get("action"), json.dumps(rec.get("params", {}), ensure_ascii=False),
                rec.get("risk_level", "high"), rec.get("status"), rec.get("requested_by", "agent"))
        finally:
            await conn.close()
    except Exception:  # noqa: BLE001  闸门饱和 → 仅镜像（审批不丢）
        pass
    await mirror_approval_to_redis(rec)
    return rec


async def resolve_approval(dsn: str, approval_id: str, decision: str, by: str) -> Optional[dict]:
    import time as _t
    rec = None
    try:
        conn = await _connect_kwargs_from_dsn(dsn, timeout_s=10)
        try:
            r = await conn.fetchrow(f"""
            UPDATE {APPROVALS_TABLE} SET status=$2, decided_by=$3, decided_at=now()
            WHERE approval_id=$1 AND status='pending' RETURNING *
            """, approval_id, decision, by)
            rec = dict(r) if r else None
        finally:
            await conn.close()
    except Exception:  # noqa: BLE001
        pass
    if rec is None:
        rec = await _read_approval_mirror(approval_id)
        if rec is None or rec.get("status") != "pending":
            return None  # 不存在或已决议
        rec["status"] = decision
        rec["decided_by"] = by
        rec["decided_at"] = _t.time()
    if isinstance(rec.get("params"), str):
        rec["params"] = json.loads(rec.get("params") or "{}")
    await mirror_approval_to_redis(rec)
    return rec


async def _read_approval_mirror(approval_id: str) -> Optional[dict]:
    cli, ok = await _redis_fallback()
    if not ok:
        return None
    try:
        raw = await cli.get(f"dataagent:approval:{approval_id}")
        return json.loads(raw) if raw else None
    except Exception:  # noqa: BLE001
        return None


async def get_approval(dsn: str, approval_id: str) -> Optional[dict]:
    try:
        conn = await _connect_kwargs_from_dsn(dsn, timeout_s=6)
        try:
            r = await conn.fetchrow(f"SELECT * FROM {APPROVALS_TABLE} WHERE approval_id=$1", approval_id)
            if r:
                rec = dict(r)
                rec["params"] = json.loads(rec.get("params") or "{}")
                return rec
        finally:
            await conn.close()
    except Exception:  # noqa: BLE001
        pass
    return await _read_approval_mirror(approval_id)


async def list_approvals(dsn: str, status: str = "pending", limit: int = 20) -> list:
    try:
        conn = await _connect_kwargs_from_dsn(dsn, timeout_s=6)
        try:
            rows = await conn.fetch(
                f"SELECT * FROM {APPROVALS_TABLE} WHERE status=$1 ORDER BY created_at DESC LIMIT $2",
                status, limit)
            out = []
            for r in rows:
                d = dict(r)
                d["params"] = json.loads(d.get("params") or "{}")
                out.append(d)
            return out
        finally:
            await conn.close()
    except Exception:  # noqa: BLE001
        return []
