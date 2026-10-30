# -*- coding: utf-8 -*-
"""全链路真机 E2E（GAP-35 收口）：API 入队 → Pulsar → Worker 执行 → manual 审批挂起
→ API resolve（真实 HITL resume）→ Worker 恢复执行 → succeeded → CRDB 三表断言。

用法（仓库根）:
    python scripts/realenv/e2e_full_chain.py --base http://10.167.2.175:30080
前置：dataagent-prod worker 使用 USE_PULSAR=true + manual 模式（现场已配置）。
退出码 0/1；每步打印证据。CRDB 断言经 kubectl exec（SSH 编排由调用方/人工完成时
可加 --skip-crdb；默认尝试通过 ssh root@10.167.2.175 kubectl exec）。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import uuid

import httpx

BASE_DEFAULT = "http://10.167.2.175:30080"
RESULTS: list[tuple[str, bool, str]] = []


def step(name: str, fn):
    try:
        fn()
        RESULTS.append((name, True, ""))
        print(f"  ✓ {name}", flush=True)
    except AssertionError as e:
        RESULTS.append((name, False, str(e)))
        print(f"  ✗ {name}: {e}", flush=True)
    except Exception as e:  # noqa: BLE001
        RESULTS.append((name, False, f"{type(e).__name__}: {e}"))
        print(f"  ✗ {name}: {type(e).__name__}: {e}", flush=True)


def _assert(cond, detail=""):
    if not cond:
        raise AssertionError(f"实际={detail}")


def crdb_assert_via_ssh(task_id: str, host: str) -> tuple[bool, str]:
    """经 SSH→kubectl exec→asyncpg 断言 CRDB 三表（两跳文件投递，避免嵌套引号超时）。"""
    import base64 as _b64
    py = (
        "import asyncio, os, asyncpg, json, sys\n"
        "task_id = sys.argv[1]\n"
        "async def q():\n"
        "    conn = await asyncpg.connect(os.getenv(\"DATAAGENT_DATABASE_URL\"), timeout=8)\n"
        "    t = await conn.fetch(\"SELECT task_id, status, run_id FROM dataagent_tasks WHERE task_id=$1\", task_id)\n"
        "    a = await conn.fetch(\"SELECT approval_id, status FROM dataagent_approvals WHERE task_id=$1\", task_id)\n"
        "    rid = t[0][\"run_id\"] if t else \"\"\n"
        "    r = await conn.fetch(\"SELECT run_id, status FROM dataagent_runs WHERE run_id=$1\", rid) if rid else []\n"
        "    out = {\"task\": dict(t[0]) if t else None, \"approval\": dict(a[0]) if a else None, \"run\": dict(r[0]) if r else None}\n"
        "    print(json.dumps(out))\n"
        "    await conn.close()\n"
        "asyncio.run(q())\n"
    )
    b64 = _b64.b64encode(py.encode()).decode()
    remote_cmd = (
        "POD=$(kubectl get pods -n dataagent-prod -l app=dataagent-worker "
        "-o jsonpath='{.items[0].metadata.name}'); "
        f"echo {b64} | kubectl exec -i -n dataagent-prod $POD -- sh -c 'base64 -d > /tmp/_crdb_assert.py'; "
        "kubectl exec -n dataagent-prod $POD -- python /tmp/_crdb_assert.py " + task_id
    )
    try:
        out = subprocess.run(["ssh", f"root@{host}", remote_cmd],
                             capture_output=True, text=True, timeout=90,
                             encoding="utf-8", errors="replace")
        line = [l for l in out.stdout.splitlines() if l.strip().startswith("{")]
        if not line:
            return False, f"无输出: {out.stdout[-160:]} {out.stderr[-160:]}"
        d = json.loads(line[0])
        ok = (d.get("task", {}) or {}).get("status") == "succeeded" \
            and (d.get("approval", {}) or {}).get("status") == "approved" \
            and bool((d.get("run", {}) or {}).get("run_id"))
        return ok, json.dumps(d, ensure_ascii=False)[:220]
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE_DEFAULT)
    ap.add_argument("--ssh-host", default="10.167.2.175")
    ap.add_argument("--skip-crdb", action="store_true")
    args = ap.parse_args()

    rid = f"e2e-chain-{uuid.uuid4().hex[:8]}"
    client = httpx.Client(base_url=args.base, timeout=20.0)

    rid_holder: dict = {}

    with client as c:
        step("1 登录（CRDB 种子用户，JWT）", lambda: (
            (_r := c.post("/login", json={"username": "admin", "password": "admin123"}))
            and _assert(_r.status_code == 201 and _r.json().get("token"), _r.status_code)))
        H = {"Authorization": "Bearer " + c.post(
            "/login", json={"username": "admin", "password": "admin123"}).json()["token"]}

        def poll_task(statuses, timeout_s=90):
            t0 = time.time()
            last = ""
            task_id = rid_holder.get("task_id", "")
            while time.time() - t0 < timeout_s:
                r = c.get(f"/v1/tasks/{task_id}", headers=H)
                if r.status_code == 200:
                    last = r.json().get("status", "")
                    if last in statuses:
                        return last
                time.sleep(2)
            return f"timeout(最后状态={last})"

        def _enqueue():
            r = c.post("/v1/analysis", headers=H,
                       json={"query": "全链路E2E：华东区 GMV 下滑诊断", "tenant_id": "ten_a",
                             "user_id": "u1", "idempotency_key": rid, "async_": True})
            _assert(r.status_code in (200, 201, 202) and r.json().get("status") == "queued",
                    r.text[:120])
            # GAP-35 教训：task_id 由服务端生成（req_*），必须从响应取而非自造
            rid_holder["task_id"] = r.json().get("task_id") or r.json().get("request_id")
            _assert(bool(rid_holder["task_id"]), r.text[:120])

        step("2 异步入队（API → 队列真实通道）", _enqueue)

        step("3 Worker 消费执行 → manual 审批挂起（waiting_approval）", lambda: _assert(
            poll_task({"waiting_approval"}) == "waiting_approval"))

        approval_id_holder: dict = {}

        def _find_approval():
            r = c.get("/v1/admin/approvals", headers=H)
            _assert(r.status_code == 200, r.status_code)
            items = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
            task_id = rid_holder.get("task_id", "")
            mine = [a for a in items if a.get("task_id") == task_id
                    and a.get("status") == "pending"]
            _assert(bool(mine), f"task_id={task_id} 的 pending 审批单未找到"
                       f"（pending 总数={len(items) if isinstance(items, list) else '?'}）")
            approval_id_holder["id"] = mine[0].get("approval_id") or mine[0].get("id")

        step("4 审批单真实创建（CRDB approvals pending，按 task_id 精确匹配）", _find_approval)

        def _resolve():
            r = c.post(f"/v1/admin/approvals/{approval_id_holder['id']}/resolve", headers=H,
                       json={"decision": "approved"})
            _assert(r.status_code in (200, 201), f"{r.status_code} {r.text[:120]}")
            _assert(r.json().get("task_status") in ("succeeded", "failed", "resume_pending"),
                    r.json().get("task_status"))

        step("5 API resolve approved → Worker 恢复执行（真实 HITL resume）", _resolve)

        step("6 恢复后终态 succeeded（run_id 落 run 行）", lambda: _assert(
            poll_task({"succeeded"}) == "succeeded"))

    if not args.skip_crdb:
        step("7 CRDB 三表断言（task/approval/run）", lambda: _assert(
            *crdb_assert_via_ssh(rid_holder.get("task_id", ""), args.ssh_host)))

    print("=" * 72)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    for name, ok, detail in RESULTS:
        print(f"  {'✓ PASS' if ok else '✗ ' + detail}  {name}")
    print("-" * 72)
    print(f"全链路 E2E：通过 {passed}/{len(RESULTS)} | 任务={rid}")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
