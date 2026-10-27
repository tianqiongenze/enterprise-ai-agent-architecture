# -*- coding: utf-8 -*-
"""管理域 API（B 端控制台后端）：租户/指标注册中心/模型路由/Capability权限矩阵/
Memory 管理/审批中心/任务中心/发布与灰度/概览。

全部带 RBAC 域校验（auth.User.can），数据 CRDB 主存 + Redis 镜像兜底（闸门韧性）。
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

from litestar import Request
from litestar.exceptions import HTTPException

from services.api.auth import User

DSN = os.getenv("DATAAGENT_DATABASE_URL", "")


def require(user: User, domain: str) -> None:
    if user is None:
        raise HTTPException(status_code=401, detail="未认证")
    if not user.can(domain):
        raise HTTPException(status_code=403, detail=f"角色 {user.role} 无 {domain} 权限")


async def _conn():
    from dataagent.infra.persistence import cockroach as cr
    return await cr._connect_kwargs_from_dsn(DSN, timeout_s=8)


async def _redis():
    from dataagent.infra.persistence import cockroach as cr
    cli, ok = await cr._redis_fallback()
    return cli if ok else None


# ================= 租户管理 =================
TENANT_COLS = "tenant_id,name,plan,roles,row_filter,col_filter,status,quota_rps,created_at"


async def ensure_tenant_table() -> None:
    conn = await _conn()
    try:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS dataagent_tenants(
            tenant_id TEXT PRIMARY KEY, name TEXT, plan TEXT DEFAULT 'standard',
            roles TEXT DEFAULT 'analyst', row_filter TEXT, col_filter TEXT,
            status TEXT DEFAULT 'active', quota_rps INT DEFAULT 60,
            created_at TIMESTAMPTZ DEFAULT now())
        """)
        for tid, name in (("ten_1", "华东品牌旗舰店"), ("ten_2", "华南美妆专营"),
                          ("ten_a", "演示租户A"), ("ten_b", "演示租户B")):
            await conn.execute("""
            INSERT INTO dataagent_tenants(tenant_id,name) VALUES($1,$2)
            ON CONFLICT (tenant_id) DO NOTHING""", tid, name)
    finally:
        await conn.close()


async def tenants_list() -> list[dict]:
    try:
        conn = await _conn()
        try:
            rows = await conn.fetch(f"SELECT {TENANT_COLS} FROM dataagent_tenants ORDER BY created_at DESC LIMIT 100")
            return [dict(r) for r in rows]
        finally:
            await conn.close()
    except Exception:  # noqa: BLE001
        cli = await _redis()
        if cli:
            raw = await cli.get("dataagent:tenants:all")
            return json.loads(raw) if raw else []
        return []


async def tenant_upsert(rec: dict) -> dict:
    conn = await _conn()
    try:
        await conn.execute("""
        INSERT INTO dataagent_tenants(tenant_id,name,plan,roles,row_filter,col_filter,status,quota_rps)
        VALUES($1,$2,$3,$4,$5,$6,$7,$8)
        ON CONFLICT (tenant_id) DO UPDATE SET name=excluded.name, plan=excluded.plan,
          roles=excluded.roles, row_filter=excluded.row_filter, col_filter=excluded.col_filter,
          status=excluded.status, quota_rps=excluded.quota_rps
        """, rec.get("tenant_id"), rec.get("name"), rec.get("plan", "standard"),
            ",".join(rec.get("roles", ["analyst"])) if isinstance(rec.get("roles"), list) else rec.get("roles", "analyst"),
            rec.get("row_filter"), rec.get("col_filter"),
            rec.get("status", "active"), int(rec.get("quota_rps", 60)))
    finally:
        await conn.close()
    cli = await _redis()
    if cli:
        await cli.set("dataagent:tenants:all", json.dumps(await tenants_list(), default=str), ex=3600)
    return rec


# ================= 指标注册中心 =================
async def ensure_metric_table() -> None:
    conn = await _conn()
    try:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS dataagent_metrics(
            name TEXT PRIMARY KEY, display_name TEXT, formula TEXT,
            aliases TEXT, dimension TEXT DEFAULT 'amount', owner TEXT DEFAULT 'platform',
            status TEXT DEFAULT 'active', version INT DEFAULT 1,
            refreshed_at TIMESTAMPTZ DEFAULT now())
        """)
        seed = [
            ("gmv", "成交总额", "已支付订单金额合计（含运费，不含退款）", "销售额,成交额,GMV", "amount"),
            ("order_count", "订单数", "去重订单数量", "单量,订单量", "count"),
            ("aov", "客单价", "GMV / 订单数", "平均订单价值", "amount"),
            ("conversion_rate", "转化率", "下单UV / 访问UV", "转化,CR", "rate"),
            ("refund_rate", "退款率", "退款订单数 / 订单数", "退货率,退款占比", "rate"),
        ]
        for n, d, f, a, dim in seed:
            await conn.execute("""
            INSERT INTO dataagent_metrics(name,display_name,formula,aliases,dimension)
            VALUES($1,$2,$3,$4,$5) ON CONFLICT (name) DO NOTHING""", n, d, f, a, dim)
    finally:
        await conn.close()


async def metrics_list() -> list[dict]:
    try:
        conn = await _conn()
        try:
            rows = await conn.fetch("SELECT * FROM dataagent_metrics ORDER BY name LIMIT 200")
            return [dict(r) for r in rows]
        finally:
            await conn.close()
    except Exception:  # noqa: BLE001
        return []


async def metric_upsert(rec: dict) -> dict:
    conn = await _conn()
    try:
        await conn.execute("""
        INSERT INTO dataagent_metrics(name,display_name,formula,aliases,dimension,owner,status)
        VALUES($1,$2,$3,$4,$5,$6,$7)
        ON CONFLICT (name) DO UPDATE SET display_name=excluded.display_name,
          formula=excluded.formula, aliases=excluded.aliases, dimension=excluded.dimension,
          owner=excluded.owner, status=excluded.status, version=dataagent_metrics.version+1,
          refreshed_at=now()
        """, rec.get("name"), rec.get("display_name"), rec.get("formula"),
            rec.get("aliases"), rec.get("dimension", "amount"),
            rec.get("owner", "platform"), rec.get("status", "active"))
    finally:
        await conn.close()
    return rec


# ================= 模型路由配置 =================
async def ensure_route_table() -> None:
    conn = await _conn()
    try:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS dataagent_model_routes(
            task TEXT PRIMARY KEY, primary_model TEXT, fallback_models TEXT,
            max_attempts INT DEFAULT 3, timeout_s INT DEFAULT 60,
            cost_cap DECIMAL DEFAULT 10, status TEXT DEFAULT 'active',
            updated_at TIMESTAMPTZ DEFAULT now())
        """)
        seed = [
            ("planning", "qwen2.5:14b", "qwen2.5-coder:7b"),
            ("conclusion", "qwen2.5:14b", "qwen3:4b"),
            ("analysis", "qwen2.5-coder:7b", "qwen2.5:14b"),
            ("sql", "qwen2.5-coder:7b", "qwen2.5:14b"),
        ]
        for t, m, fb in seed:
            await conn.execute("""
            INSERT INTO dataagent_model_routes(task,primary_model,fallback_models)
            VALUES($1,$2,$3) ON CONFLICT (task) DO NOTHING""", t, m, fb)
    finally:
        await conn.close()


async def routes_list() -> list[dict]:
    try:
        conn = await _conn()
        try:
            rows = await conn.fetch("SELECT * FROM dataagent_model_routes ORDER BY task")
            return [dict(r) for r in rows]
        finally:
            await conn.close()
    except Exception:  # noqa: BLE001
        return []


async def route_upsert(rec: dict) -> dict:
    conn = await _conn()
    try:
        fb = ",".join(rec["fallback_models"]) if isinstance(rec.get("fallback_models"), list) else rec.get("fallback_models", "")
        await conn.execute("""
        INSERT INTO dataagent_model_routes(task,primary_model,fallback_models,max_attempts,timeout_s,cost_cap,status)
        VALUES($1,$2,$3,$4,$5,$6,$7)
        ON CONFLICT (task) DO UPDATE SET primary_model=excluded.primary_model,
          fallback_models=excluded.fallback_models, max_attempts=excluded.max_attempts,
          timeout_s=excluded.timeout_s, cost_cap=excluded.cost_cap,
          status=excluded.status, updated_at=now()
        """, rec.get("task"), rec.get("primary_model"), fb,
            int(rec.get("max_attempts", 3)), int(rec.get("timeout_s", 60)),
            rec.get("cost_cap", 10), rec.get("status", "active"))
    finally:
        await conn.close()
    return rec


# ================= Capability / 权限矩阵 =================
def capability_matrix() -> dict:
    """来自内核 CapabilityRegistry（真实注册的工具）+ 角色可见性规则。"""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "dataagent", "src"))
    from dataagent.app.container import DataAgentContainer, default_seed
    c = DataAgentContainer(seed_orders=default_seed())
    tools = []
    for name, t in c.tools.all().items():
        tools.append({
            "name": name, "description": t.description[:60],
            "risk_level": t.risk_level.value, "requires_approval": t.requires_approval,
            "owner": t.owner, "version": t.version,
            "visible_roles": ["admin", "approver"] if t.risk_level.value in ("high", "medium") else ["admin", "approver", "analyst"],
        })
    skills = [{"name": s.name, "mission": s.mission[:60]} for s in
              [c.skills.get("anomaly_diagnosis")] if s]
    return {"tools": tools, "skills": skills,
            "roles": {"admin": "全部能力+治理", "approver": "高风险工具+审批",
                      "analyst": "只读工具", "viewer": "只读任务"}}


# ================= Memory 管理 =================
async def memory_list(tenant_id: str = "ten_a", limit: int = 50) -> list[dict]:
    from dataagent.infra.persistence import cockroach as cr
    try:
        store = cr.CockroachMemoryStore(DSN)
        await store._ensure()
        hits = await store.search_candidates("", tenant_id, "u1", limit=limit)
        return [{"memory_id": m.memory_id, "key": m.key, "content": m.content,
                 "scope": m.scope.value, "version": m.version, "active": m.active} for m in hits]
    except Exception:  # noqa: BLE001
        return []


async def memory_write(rec: dict) -> dict:
    from dataagent.infra.persistence import cockroach as cr
    from dataagent.infra.memory.memory import Memory, MemoryScope
    store = cr.CockroachMemoryStore(DSN)
    await store._ensure()
    m = Memory(scope=MemoryScope(rec.get("scope", "user")), owner=rec.get("owner", "u1"),
               tenant_id=rec.get("tenant_id", "ten_a"), key=rec["key"], content=rec["content"])
    await store.put(m)
    return {"memory_id": m.memory_id, "key": m.key}


async def memory_delete(memory_id: str, tenant_id: str) -> bool:
    from dataagent.infra.persistence import cockroach as cr
    store = cr.CockroachMemoryStore(DSN)
    await store._ensure()
    return await store.delete(memory_id, tenant_id)


# ================= 审批中心 =================
async def approvals_list(status: str = "pending") -> list[dict]:
    from dataagent.infra.persistence import cockroach as cr
    try:
        rows = await cr.list_approvals(DSN, status=status, limit=50)
        if rows:
            return rows
    except Exception:  # noqa: BLE001
        pass
    # CRDB 闸门/空表 → Redis 镜像兜底
    try:
        cli = await _redis()
        if cli:
            ids = await cli.smembers("dataagent:approvals:pending") if status == "pending" else []
            out = []
            for i in list(ids)[:50]:
                raw = await cli.get(f"dataagent:approval:{i.decode() if isinstance(i, bytes) else i}")
                if raw:
                    out.append(json.loads(raw))
            return out
    except Exception:  # noqa: BLE001
        pass
    return []


async def approval_create(rec: dict) -> dict:
    from dataagent.infra.persistence import cockroach as cr
    return await cr.create_approval(DSN, rec)


async def approval_resolve(approval_id: str, decision: str, by: str) -> Optional[dict]:
    from dataagent.infra.persistence import cockroach as cr
    return await cr.resolve_approval(DSN, approval_id, decision, by)


async def approval_get(approval_id: str) -> Optional[dict]:
    from dataagent.infra.persistence import cockroach as cr
    return await cr.get_approval(DSN, approval_id)


# ================= 任务中心 =================
async def tasks_list(status: str = "", limit: int = 50) -> list[dict]:
    from dataagent.infra.persistence import cockroach as cr
    try:
        conn = await _conn()
        try:
            if status:
                rows = await conn.fetch(
                    "SELECT * FROM dataagent_tasks WHERE status=$1 ORDER BY updated_at DESC LIMIT $2",
                    status, limit)
            else:
                rows = await conn.fetch(
                    "SELECT * FROM dataagent_tasks ORDER BY updated_at DESC LIMIT $2", limit)
            return [dict(r) for r in rows]
        finally:
            await conn.close()
    except Exception:  # noqa: BLE001  闸门/表缺失 → Redis 镜像
        out = await cr.list_tasks_mirror(limit=limit)
        if status:
            out = [t for t in out if t.get("status") == status]
        return out


async def task_get(task_id: str) -> Optional[dict]:
    from dataagent.infra.persistence import cockroach as cr
    try:
        return await cr.get_task(DSN, task_id)
    except Exception:  # noqa: BLE001
        return await cr.read_task_mirror(task_id)


# ================= 发布与灰度 =================
RELEASE_DEFAULT = {"version": "0.2.0", "canary_pct": 0, "kill_switch": False,
                   "regression_gate": {"code": 0.8}, "history": [],
                   "released_versions": ["0.1.0", "0.2.0"]}


async def release_state() -> dict:
    cli = await _redis()
    if cli:
        raw = await cli.get("dataagent:release:state")
        if raw:
            return json.loads(raw)
    try:
        conn = await _conn()
        try:
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS dataagent_release(
                id INT PRIMARY KEY DEFAULT 1, state JSONB, updated_at TIMESTAMPTZ DEFAULT now())
            """)
            r = await conn.fetchrow("SELECT state FROM dataagent_release WHERE id=1")
            if r:
                return json.loads(r["state"])
        finally:
            await conn.close()
    except Exception:  # noqa: BLE001
        pass
    return dict(RELEASE_DEFAULT)


async def release_save(state: dict) -> dict:
    cli = await _redis()
    if cli:
        await cli.set("dataagent:release:state", json.dumps(state, ensure_ascii=False))
    try:
        conn = await _conn()
        try:
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS dataagent_release(
                id INT PRIMARY KEY DEFAULT 1, state JSONB, updated_at TIMESTAMPTZ DEFAULT now())
            """)
            await conn.execute("""
            INSERT INTO dataagent_release(id, state, updated_at) VALUES(1,$1,now())
            ON CONFLICT (id) DO UPDATE SET state=excluded.state, updated_at=now()
            """, json.dumps(state, ensure_ascii=False))
        finally:
            await conn.close()
    except Exception:  # noqa: BLE001
        pass
    return state


# ================= 概览 Dashboard =================
async def dashboard() -> dict:
    from dataagent.infra.persistence import cockroach as cr
    out: dict[str, Any] = {"service": "dataagent", "version": "0.2.0"}
    try:
        conn = await _conn()
        try:
            out["tasks_total"] = await conn.fetchval("SELECT count(*) FROM dataagent_tasks")
            out["tasks_succeeded"] = await conn.fetchval(
                "SELECT count(*) FROM dataagent_tasks WHERE status='succeeded'")
            out["tasks_waiting"] = await conn.fetchval(
                "SELECT count(*) FROM dataagent_tasks WHERE status='waiting_approval'")
            out["tenants"] = await conn.fetchval("SELECT count(*) FROM dataagent_tenants")
            out["metrics"] = await conn.fetchval("SELECT count(*) FROM dataagent_metrics")
        finally:
            await conn.close()
    except Exception:  # noqa: BLE001
        out["tasks_total"] = out.get("tasks_total", 0) or 0
    try:
        rows = await cr.read_summary_mirror()
        out["top_regions"] = rows[:3] if rows else []
    except Exception:  # noqa: BLE001
        out["top_regions"] = []
    try:
        out["approvals_pending"] = len(await approvals_list("pending"))
    except Exception:  # noqa: BLE001
        out["approvals_pending"] = 0
    return out


# ================= 启动引导 =================
def try_bootstrap() -> None:
    import asyncio as _a
    if not DSN:
        return
    async def _b():
        from dataagent.infra.persistence import cockroach as cr
        for fn in (ensure_tenant_table, ensure_metric_table, ensure_route_table,
                   cr.ensure_task_tables):
            try:
                await fn()
            except Exception:  # noqa: BLE001
                pass
    try:
        _a.run(_b())
    except Exception:  # noqa: BLE001
        pass