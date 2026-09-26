# -*- coding: utf-8 -*-
"""regionMetrics 汇总表引导/刷新脚本（许可闸门韧性）。

共享 CockroachDB 免费许可的"并发打开事务 ≤10"是集群级上限，被其他负载占满时
连 SELECT 1 都会被拒。本脚本带"无限重试+指数退避"，闸门一开就：
  1) 建汇总表 orders_region_summary
  2) 全量聚合 orders（≥1亿行，语句超时 15 分钟）
  3) 写 Redis 镜像（24h TTL）
用法:
  python scripts/refresh_region_summary.py            # 前台重试直到成功
  python scripts/refresh_region_summary.py --once     # 单次尝试（给 K8S Job 用）
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dataagent", "src"))

DSN = os.getenv("DATAAGENT_DATABASE_URL", "postgresql://root@10.167.2.175:30257/dataagent")


async def once() -> bool:
    from dataagent.infra.persistence import cockroach as cr
    await cr.ensure_summary_table(DSN)
    cnt = await cr.refresh_region_summary(DSN)
    print(f"[refresh] summary rows={cnt}", flush=True)
    if cnt:
        conn = await cr._connect_kwargs_from_dsn(DSN, timeout_s=10)
        try:
            rows = [dict(r) for r in await conn.fetch(
                "SELECT region, orders, gmv FROM orders_region_summary "
                "WHERE tenant_id='ten_1' ORDER BY gmv DESC LIMIT 5")]
        finally:
            await conn.close()
        await cr.mirror_summary_to_redis(rows)
        print(f"[mirror] redis rows={len(rows)}", flush=True)
    return bool(cnt)


async def main(run_once: bool):
    attempt = 0
    while True:
        attempt += 1
        try:
            ok = await once()
            if ok:
                print("[done] summary refreshed", flush=True)
                return 0
        except Exception as e:  # noqa: BLE001
            print(f"[attempt {attempt}] gated/failed: {str(e)[:100]}", flush=True)
        if run_once:
            return 1
        await asyncio.sleep(min(30 * attempt, 300))


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main("--once" in sys.argv)))