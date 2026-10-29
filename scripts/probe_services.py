# -*- coding: utf-8 -*-
"""服务层探针脚本（对齐参照工程 tools/probe_http.sh 的方法论）。

原则（第 41 课）：`/healthz` 返回 200 说明不了服务能用 —— 探针要**真的发请求、
逐项校验状态码、结束清理**。本脚本提供两种模式：

1. **asgi 模式（默认）**：进程内 TestClient 直接打 ASGI app —— 无需端口、
   无需 granian、CI 友好；覆盖 23 项检查（探活/认证/RBAC/业务/管理面）。
2. **http 模式**（--mode http）：真实起 granian 子进程 + HTTP 请求 ——
   部署态验证；结束按平台清理**进程树**（Windows: taskkill /T；POSIX: 进程组），
   防"只杀父进程留下占用端口的孤儿 worker"（参照工程 §8 的真实教训）。

运行：仓库根目录 `python scripts/probe_services.py [--mode asgi|http] [--port 8123]`
退出码：0=全部通过；1=存在失败（逐项打印 ✗）。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in ("services/src", "dataagent/src"):
    sys.path.insert(0, str(ROOT / p))

CHECKS: list[tuple[str, str]] = []  # (名称, 结果 PASS/✗+原因)


def check(name: str, fn) -> bool:
    try:
        fn()
        CHECKS.append((name, "PASS"))
        return True
    except AssertionError as e:
        CHECKS.append((name, f"✗ {e}"))
        return False
    except Exception as e:  # noqa: BLE001
        CHECKS.append((name, f"✗ 异常: {type(e).__name__}: {e}"))
        return False


def _assert(cond: bool, detail) -> None:
    if not cond:
        raise AssertionError(f"实际={detail}")


def login_headers(c, username: str = "admin", password: str = "admin123") -> dict:
    r = c.post("/login", json={"username": username, "password": password})
    assert r.status_code == 201, f"登录失败: {r.status_code} {r.text[:120]}"
    return {"Authorization": "Bearer " + r.json()["token"]}


def analyst_headers(c) -> dict:
    r = c.post("/login", json={"username": "analyst", "password": "analyst123"})
    assert r.status_code == 201, f"analyst 登录失败: {r.status_code}"
    return {"Authorization": "Bearer " + r.json()["token"]}


def run_checks(client) -> int:
    """对任意"有 .get/.post 的客户端"（TestClient 或 httpx.Client）跑全部探针。"""
    with client as c:
        # ---- 探活与管理面公开端点 ----
        results: list[bool] = []
        results.append(check("GET /healthz → 200", lambda: (
            (_r := c.get("/healthz")) and _assert(_r.status_code == 200, _r.status_code))))
        results.append(check("GET /readyz → 200", lambda: (
            (_r := c.get("/readyz")) and _assert(_r.status_code == 200, _r.status_code))))
        results.append(check("GET /metrics → 200", lambda: (
            (_r := c.get("/metrics")) and _assert(_r.status_code == 200, _r.status_code))))
        results.append(check("GET / (SPA) → 200", lambda: (
            (_r := c.get("/")) and _assert(_r.status_code == 200, _r.status_code))))
        results.append(check("GET /console → 200", lambda: (
            (_r := c.get("/console")) and _assert(_r.status_code == 200, _r.status_code))))

        # ---- 认证门禁 ----
        results.append(check("POST /login 错误密码 → 401", lambda: (
            (_r := c.post("/login", json={"username": "admin", "password": "wrong"}))
            and _assert(_r.status_code in (401, 400), _r.status_code))))
        results.append(check("POST /login admin → 201+token", lambda: (
            (_r := c.post("/login", json={"username": "admin", "password": "admin123"}))
            and _assert(_r.status_code == 201 and _r.json().get("token"), _r.status_code))))

        ADMIN = login_headers(c)
        ANALYST = analyst_headers(c)

        # ---- 未认证拦截 ----
        results.append(check("GET /v1/tasks 无凭据 → 401", lambda: (
            (_r := c.get("/v1/admin/tasks")) and _assert(_r.status_code in (401, 403), _r.status_code))))

        # ---- 业务面 ----
        results.append(check("POST /v1/analysis 同步 → succeeded/waiting", lambda: (
            (_r := c.post("/v1/analysis", headers=ADMIN,
                          json={"query": "华东区 GMV 下滑诊断", "tenant_id": "ten_a"}))
            and _assert(_r.status_code in (200, 201), _r.status_code)
            and _assert(_r.json().get("status") in ("succeeded", "waiting_approval"), _r.text[:120]))))
        results.append(check("POST /v1/analysis 异步入队 → 2xx", lambda: (
            (_r := c.post("/v1/analysis", headers=ADMIN,
                          json={"query": "华南区订单量分析", "async_": True}))
            and _assert(_r.status_code in (200, 201, 202), _r.status_code))))
        results.append(check("GET /v1/admin/tasks → 200", lambda: (
            (_r := c.get("/v1/admin/tasks", headers=ADMIN))
            and _assert(_r.status_code == 200, _r.status_code))))
        results.append(check("GET /v1/admin/dashboard → 200", lambda: (
            (_r := c.get("/v1/admin/dashboard", headers=ADMIN))
            and _assert(_r.status_code == 200, _r.status_code))))

        # ---- 管理面（RBAC 差异）----
        for name, path in (
            ("tenants", "/v1/admin/tenants"), ("metrics", "/v1/admin/metrics"),
            ("routes", "/v1/admin/routes"), ("capability", "/v1/admin/capability"),
            ("memory", "/v1/admin/memory"), ("approvals", "/v1/admin/approvals"),
            ("release", "/v1/admin/release"),
        ):
            results.append(check(f"GET {path} (admin) → 200", lambda path=path: (
                (_r := c.get(path, headers=ADMIN)) and _assert(_r.status_code == 200, _r.status_code))))
        results.append(check("GET /v1/admin/tenants (analyst) → 403", lambda: (
            (_r := c.get("/v1/admin/tenants", headers=ANALYST))
            and _assert(_r.status_code == 403, _r.status_code))))

        # ---- 审批单路径 ----
        results.append(check("GET /v1/admin/approvals/{bad-id} → 4xx", lambda: (
            (_r := c.get("/v1/admin/approvals/nonexistent-id", headers=ADMIN))
            and _assert(_r.status_code in (404, 400), _r.status_code))))
        results.append(check("POST resolve bad-id → 4xx", lambda: (
            (_r := c.post("/v1/admin/approvals/nonexistent-id/resolve", headers=ADMIN,
                          json={"decision": "approved"}))
            and _assert(_r.status_code in (404, 400), _r.status_code))))

        # ---- 未知路由 ----
        results.append(check("GET /v1/nope → 404", lambda: (
            (_r := c.get("/v1/nope", headers=ADMIN)) and _assert(_r.status_code == 404, _r.status_code))))

    # ---- 汇总 ----
    print("=" * 72)
    passed = sum(1 for _, s in CHECKS if s == "PASS")
    for name, status in CHECKS:
        if status == "PASS":
            print(f"  ✓ PASS  {name}")
        else:
            print(f"  ✗ {status}  {name}")
    print("-" * 72)
    print(f"通过 {passed}/{len(CHECKS)}")
    return 0 if passed == len(CHECKS) else 1


def run_asgi_probes() -> int:
    from services.api.asgi import app

    try:
        from litestar.testing import TestClient
    except ImportError:
        print("✗ litestar 未安装 —— asgi 探针不可用。安装: pip install litestar")
        sys.exit(1)
    return run_checks(TestClient(app))


# ---------------- http 模式（部署态验证） ----------------

def _kill_tree(pid: int) -> None:
    """按平台清理进程树（防孤儿 worker 占端口——参照工程 §8 教训）。"""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, check=False)
    else:
        import signal
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except ProcessLookupError:
            pass


def run_http_probes(port: int, timeout_s: float = 30.0) -> int:
    """真实起 granian 子进程 + HTTP 探针 + 进程树清理。"""
    import httpx

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([
        str(ROOT / "services" / "src"), str(ROOT / "dataagent" / "src"),
        env.get("PYTHONPATH", ""),
    ])
    env.setdefault("DATAAGENT_APPROVAL_MODE", "auto")
    cmd = [sys.executable, "-m", "granian", "--interface", "asgi",
           "--host", "127.0.0.1", "--port", str(port), "--workers", "1",
           "services.api.asgi:app"]
    print(f"== 启动 granian（port={port}, workers=1, 进程树将随探针结束清理） ==")
    proc = subprocess.Popen(cmd, env=env, cwd=str(ROOT))
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + timeout_s
        ready = False
        while time.time() < deadline:
            try:
                if httpx.get(f"{base}/healthz", timeout=2.0).status_code == 200:
                    ready = True
                    break
            except Exception:  # noqa: BLE001
                time.sleep(0.5)
        if not ready:
            print("✗ granian 在超时内未就绪")
            return 1
        client = httpx.Client(base_url=base, timeout=15.0)
        return run_checks(client)
    finally:
        _kill_tree(proc.pid)
        print("== granian 进程树已清理 ==")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("asgi", "http"), default="asgi")
    ap.add_argument("--port", type=int, default=8123)
    ap.add_argument("--base-url", default="",
                    help="http 模式直接指定目标（如 http://10.167.2.175:30080），跳过本地 granian 子进程")
    args = ap.parse_args()
    if args.mode == "http":
        if args.base_url:
            import httpx
            print(f"== 直连目标 {args.base_url}（真实部署验收模式） ==")
            return run_checks(httpx.Client(base_url=args.base_url, timeout=15.0))
        return run_http_probes(args.port)
    return run_asgi_probes()


if __name__ == "__main__":
    sys.exit(main())
