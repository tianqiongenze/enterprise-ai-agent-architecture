# -*- coding: utf-8 -*-
"""Worker 端到端探针（GAP-14/19 收口验证）：入队 → 租约领取 → 消费执行 → 确认释放。

链路（全部离线，memory 后端）：
    POST /v1/analysis async_=true（asgi，memory 队列）
    → worker.run_once()（租约 acquire → process → ack → release）
    → 断言队列清空 / 终态 / 租约已归还

运行：仓库根目录 `python scripts/probe_worker.py`，退出码 0/1。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# env 必须在导入 services/dataagent 前设置（container 构建读取）
os.environ["DATAAGENT_QUEUE_BACKEND"] = "memory"
os.environ["DATAAGENT_APPROVAL_MODE"] = "auto"
for p in ("services/src", "dataagent/src"):
    sys.path.insert(0, str(ROOT / p))


def main() -> int:
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, fn):
        try:
            fn()
            checks.append((name, True, ""))
        except AssertionError as e:
            checks.append((name, False, str(e)))
        except Exception as e:  # noqa: BLE001
            checks.append((name, False, f"{type(e).__name__}: {e}"))

    def _assert(cond, detail=""):
        if not cond:
            raise AssertionError(f"实际={detail}")

    from litestar.testing import TestClient

    from services.api.asgi import app
    from services.shared import queue as q

    with TestClient(app) as c:
        r = c.post("/login", json={"username": "admin", "password": "admin123"})
        H = {"Authorization": "Bearer " + r.json()["token"]}

        check("POST /v1/analysis async → queued", lambda: (
            (_r := c.post("/v1/analysis", headers=H,
                          json={"query": "华东区 GMV 下滑诊断", "tenant_id": "ten_a",
                                "async_": True}))
            and _assert(_r.status_code in (200, 201), _r.status_code)
            and _assert(_r.json().get("status") == "queued", _r.text[:120])))
        check("memory 队列深度 = 1", lambda: _assert(q.mem_queue_depth() == 1, q.mem_queue_depth()))

        # ---- worker 消费（租约领取 → 执行 → ack → release）----
        from services.worker import main as w

        task_id_holder: dict = {}

        def _consume_and_check():
            final = w.run_once()
            _assert(final == "succeeded", final)
            # 找到刚消费的任务（队列为空 → 从 worker 侧验证租约已释放）
            task_id_holder["last"] = final

        check("worker.run_once() → succeeded（租约领取+执行+ack+release）", _consume_and_check)
        check("队列清空", lambda: _assert(q.mem_queue_depth() == 0, q.mem_queue_depth()))

        def _lease_released():
            # 任一租约都不应仍被当前 worker 持有（已 ack release）
            held = [t for t, l in w._LEASES._leases.items()
                    if l.released_at is None and l.owner == w.WORKER_ID]
            _assert(held == [], held)

        check("租约已归还（无未释放持有）", _lease_released)

        check("空队列 run_once → None", lambda: _assert(w.run_once() is None, "should be None"))

    print("=" * 72)
    passed = sum(1 for _, ok, _ in checks if ok)
    for name, ok, detail in checks:
        print(f"  {'✓ PASS' if ok else '✗ ' + detail}  {name}")
    print("-" * 72)
    print(f"通过 {passed}/{len(checks)}")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
