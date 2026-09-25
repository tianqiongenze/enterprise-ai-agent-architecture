# -*- coding: utf-8 -*-
"""生成 ≥1亿行 经营明细数据到 CockroachDB（count=100亿目标可调）。从 MAX(order_id) 续写，幂等无重复。

用法: PYTHONPATH=src python scripts/gen_data.py [total_rows] [batch]
"""
from __future__ import annotations
import asyncio, asyncpg, random, datetime, time, sys, os

def make_batch(start_id: int, n: int):
    rows = []
    cats = ['鞋','服','家电','食品','美妆','数码']
    regions = ['华东','华南','华北','西南','东北','西北']
    for j in range(n):
        idx = start_id + j
        rows.append((idx, 'ten_'+str(random.randint(1,50)), random.choice(regions),
            random.choice(cats), round(random.uniform(50,5000),2),
            random.randint(1,20), round(random.uniform(0.02,0.96),4), random.random()<0.08,
            datetime.datetime(2025,1,1)+datetime.timedelta(days=random.randint(0,650), seconds=random.randint(0,86399))))
    return rows

async def run(total: int, batch: int, host: str, port: int, db: str):
    conn = await asyncio.wait_for(asyncpg.connect(host=host, port=port, user='root', database=db, timeout=8), timeout=15)
    start_id = int(await conn.fetchval("SELECT COALESCE(MAX(order_id),0)+1 FROM orders"))
    print(f"[gen] start_id={start_id} target={total}", flush=True)
    i = start_id
    t0 = time.time()
    while i <= total:
        n = min(batch, total-i+1)
        rows = make_batch(i, n)
        await conn.copy_records_to_table('orders', records=rows,
            columns=['order_id','tenant_id','region','category','amount','qty','conversion_rate','refunded','order_ts'])
        i += n
        elapsed = time.time()-t0
        print(f"  {i:,}/{total:,}  ~{n/elapsed:,.0f} rows/s", flush=True)
        t0 = time.time()
    await conn.close()
    print("[gen] done", flush=True)

if __name__ == "__main__":
    total = int(os.getenv("GEN_TOTAL", sys.argv[1] if len(sys.argv) > 1 else "100000000"))
    batch = int(os.getenv("GEN_BATCH", sys.argv[2] if len(sys.argv) > 2 else "1000000"))
    asyncio.run(run(total, batch,
        os.getenv("DATAAGENT_DATABASE_HOST","10.167.2.175"),
        int(os.getenv("DATAAGENT_DATABASE_PORT","30257")),
        os.getenv("DATAAGENT_DATABASE_NAME","dataagent")))