# -*- coding: utf-8 -*-
"""JWT 认证 + 用户/角色（大厂标准：HS256、pbkdf2 口令哈希、RBAC 角色、env 密钥）。

调研结论（Litestar 官方 security/jwt）：
- JWTAuth + AuthenticationMiddleware，retrieve_user_handler 从 sub 解析用户
- 密钥走环境变量；公共路由用 exclude
- 浏览器端用 Authorization 头（SPA 存 localStorage）
用户存储：CRDB users 表 + Redis 镜像（闸门韧性），首次启动种子 admin/analyst/approver。
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from typing import Any, Optional

from litestar.security.jwt import JWTAuth, Token

from services.shared.runtime import Settings

JWT_SECRET = os.getenv("DATAAGENT_JWT_SECRET", "dev-secret-change-in-prod-9f2c")
TOKEN_EXPIRE_SECONDS = int(os.getenv("DATAAGENT_JWT_EXPIRE_S", str(12 * 3600)))

# 角色 → 可访问的管理域（RBAC 矩阵）
ROLES = {
    "admin":   {"tenants", "metrics", "routing", "capability", "memory", "release", "approvals", "tasks", "analysis"},
    "approver": {"approvals", "tasks", "analysis"},
    "analyst": {"analysis", "tasks", "metrics"},
    "viewer":  {"tasks"},
}


class User:
    def __init__(self, username: str, role: str, full_name: str = "", tenant: str = "ten_a"):
        self.username = username
        self.role = role
        self.full_name = full_name or username
        self.tenant = tenant
        self.scopes = ROLES.get(role, set())

    def can(self, domain: str) -> bool:
        return domain in self.scopes


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(8)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 60_000)
    return f"{salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, _ = stored.split("$", 1)
    except ValueError:
        return False
    return hmac.compare_digest(hash_password(password, salt), stored)


SEED_USERS = [
    {"username": "admin", "role": "admin", "full_name": "系统管理员", "password": "admin123"},
    {"username": "approver", "role": "approver", "full_name": "审批人（王审批）", "password": "approve123"},
    {"username": "analyst", "role": "analyst", "full_name": "数据分析师（李分析）", "password": "analyst123"},
]


async def ensure_users_table(dsn: str) -> None:
    from dataagent.infra.persistence import cockroach as cr
    conn = await cr._connect_kwargs_from_dsn(dsn, timeout_s=15)
    try:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS dataagent_users(
            username TEXT PRIMARY KEY, role TEXT NOT NULL, full_name TEXT,
            password_hash TEXT NOT NULL, tenant TEXT DEFAULT 'ten_a',
            created_at TIMESTAMPTZ DEFAULT now())
        """)
        for u in SEED_USERS:
            await conn.execute("""
            INSERT INTO dataagent_users(username, role, full_name, password_hash, tenant)
            VALUES($1,$2,$3,$4,'ten_a') ON CONFLICT (username) DO NOTHING
            """, u["username"], u["role"], u["full_name"], hash_password(u["password"]))
    finally:
        await conn.close()


async def find_user(dsn: str, username: str) -> Optional[dict]:
    """CRDB 主查 + Redis 镜像兜底（闸门韧性）。"""
    from dataagent.infra.persistence import cockroach as cr
    import json as _json
    cli, ok = await cr._redis_fallback()
    if ok:
        try:
            raw = await cli.get(f"dataagent:user:{username}")
            if raw:
                return _json.loads(raw)
        except Exception:  # noqa: BLE001
            pass
    try:
        conn = await cr._connect_kwargs_from_dsn(dsn, timeout_s=6)
        try:
            r = await conn.fetchrow("SELECT * FROM dataagent_users WHERE username=$1", username)
            rec = dict(r) if r else None
        finally:
            await conn.close()
        if rec and ok:
            try:
                await cli.set(f"dataagent:user:{username}", _json.dumps(rec, default=str), ex=86400)
            except Exception:  # noqa: BLE001
                pass
        return rec
    except Exception:  # noqa: BLE001  闸门饱和
        return None


async def login(dsn: str, username: str, password: str) -> Optional[User]:
    rec = await find_user(dsn, username)
    if not rec or not verify_password(password, rec.get("password_hash", "")):
        return None
    return User(rec["username"], rec.get("role", "viewer"), rec.get("full_name", ""),
                rec.get("tenant", "ten_a"))


# ---------------- Litestar JWTAuth 接线 ----------------
_DSN = os.getenv("DATAAGENT_DATABASE_URL", "")

# 启动时尽力建表+种子（闸门饱和时静默，登录走 401 提示重试）
_asyncio = None


def _get_asyncio():
    global _asyncio
    if _asyncio is None:
        import asyncio as _a
        _asyncio = _a
    return _asyncio


async def retrieve_user_handler(token: "Token", connection: Any = None) -> Optional[User]:
    """JWT sub=用户名 → 内存 User（含角色与 scopes）。"""
    try:
        rec = await find_user(_DSN, token.sub)
        if rec:
            return User(rec["username"], rec.get("role", "viewer"), rec.get("full_name", ""),
                        rec.get("tenant", "ten_a"))
    except Exception:  # noqa: BLE001
        pass
    return User(token.sub, token.sub if token.sub in ROLES else "viewer")


def make_token(user: User) -> str:
    from datetime import datetime, timedelta, timezone
    from litestar.security.jwt import Token
    t = Token(sub=user.username,
              exp=datetime.now(timezone.utc) + timedelta(seconds=TOKEN_EXPIRE_SECONDS))
    return t.encode(JWT_SECRET, algorithm="HS256")


def build_jwt_auth(exclude_paths: set[str]):
    return JWTAuth[User](
        retrieve_user_handler=retrieve_user_handler,
        token_secret=JWT_SECRET,
        exclude=exclude_paths,
        default_token_expiration=TOKEN_EXPIRE_SECONDS,
    )


def try_bootstrap_users() -> None:
    """进程启动时同步引导用户表（尽力而为，失败不阻塞服务）。"""
    if not _DSN:
        return
    try:
        aio = _get_asyncio()
        aio.run(ensure_users_table(_DSN))
    except Exception:  # noqa: BLE001
        pass
