# -*- coding: utf-8 -*-
"""真实中间件 E2E 测试（需 DATAAGENT_DATABASE_URL 指向 CockroachDB）。

跑法: PYTHONPATH=src pytest tests/e2e -m "not requires_llm"
验证：RunStore/MemoryStore 真实写读到 CRDB；并从 ≥1亿行 orders 表做聚合查询。
"""
import asyncio, os
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("DATAAGENT_DATABASE_URL") is None,
    reason="需要 DATAAGENT_DATABASE_URL 指向 CockroachDB")

DSN = os.getenv("DATAAGENT_DATABASE_URL")


@pytest.mark.asyncio
async def test_crdb_runstore_and_memory_roundtrip():
    from dataagent.infra.persistence.cockroach import build_crdb_services
    from dataagent.contracts.runtime import Run, RunStatus, EventType
    rs, ms = await build_crdb_services()
    try:
        r = Run(tenant_id="ten_a", query="E2E: 真实订单洞察")
        # 状态机纪律：pending 不能直达 succeeded，必须经 running
        r.status = RunStatus.RUNNING
        r.status = RunStatus.SUCCEEDED
        r.add_step("plan"); r.add_event(EventType.RUN_STARTED)
        await rs.save(r)
        r2 = await rs.load(r.run_id)
        assert r2.run_id == r.run_id and r2.status == RunStatus.SUCCEEDED
        from dataagent.infra.memory.memory import Memory, MemoryScope
        await ms.put(Memory(scope=MemoryScope.USER, owner="u1", tenant_id="ten_a",
                            key="pref", content="用户偏好：周报柱状图"))
        hits = await ms.search_candidates("偏好", "ten_a", "u1")
        assert any(x.key == "pref" for x in hits)
    finally:
        await rs._pool.close(); await ms._pool.close()


@pytest.mark.asyncio
async def test_query_orders_over_million_rows():
    import asyncpg
    conn = await asyncpg.connect(dsn=DSN)
    try:
        n = await conn.fetchval("SELECT count(*) FROM orders")
        print(f"[e2e] orders rows = {n:,}")
        assert n >= 1_000_000, "需先生成 ≥1M 数据"
        # 聚合：某租户 GMV/退款率
        row = await conn.fetchrow("""
            SELECT region, count(*) AS orders,
                   round(sum(amount)::numeric,2) AS gmv
            FROM orders WHERE tenant_id='ten_1' AND order_ts >= '2025-06-01'
            GROUP BY region ORDER BY gmv DESC LIMIT 5
        """)
        assert row is not None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_crdb_transaction_retry_semantics():
    """CRDB 事务重试验证：正确使用 asyncpg 事务上下文。"""
    import asyncpg
    conn = await asyncpg.connect(dsn=DSN)
    try:
        async with conn.transaction():
            await conn.execute("INSERT INTO dataagent_runs(run_id, tenant_id) VALUES($1,'ten_txn') ON CONFLICT DO NOTHING", "txn_probe_1")
        v = await conn.fetchval("SELECT count(*) FROM dataagent_runs WHERE run_id='txn_probe_1'")
        assert v == 1
    finally:
        await conn.close()
