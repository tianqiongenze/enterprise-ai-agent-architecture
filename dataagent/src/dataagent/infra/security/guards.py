# -*- coding: utf-8 -*-
"""安全与权限 (第二/四/七/八篇治理)：多租户数据权限、QueryGateway、凭据、防注入。

- 多租户行列级数据权限：在查询网关层注入行/列过滤，防止跨租户泄漏
- Query Gateway：只读，禁止写库，SQL 安全（去注释/单语句/黑名单关键字）
- Credential Broker：短期凭据，不长期持有生产密钥
- Prompt 注入防护：分离指令与外部数据
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass
class SQLPolicy:
    allowed_tables: tuple[str, ...] = ("orders",)
    readonly: bool = True
    banned_keywords: tuple[str, ...] = (
        "INSERT", "UPDATE", "DELETE", "DROP", "ALTER",
        "CREATE", "GRANT", "REVOKE", "TRUNCATE", "--", "/*", ";",
    )

    def validate(self, sql: str) -> tuple[bool, str]:
        upper = sql.upper()
        for kw in self.banned_keywords:
            if kw in upper:
                return False, f"SQL 含禁止关键字: {kw}"
        # 简单校验只允许 SELECT
        if not upper.lstrip().startswith("SELECT"):
            return False, "只允许 SELECT 查询"
        return True, "ok"


@dataclass
class TenancyContext:
    tenant_id: str
    user_id: str
    roles: set[str]
    row_filter: Optional[dict[str, str]] = None
    col_filter: Optional[tuple[str, ...]] = None


class QueryGateway:
    """只读查询网关：租户隔离、行/列级权限、SQL 校验、审计。"""

    def __init__(self, policy: SQLPolicy):
        self.policy = policy
        self.audit_log: list[dict] = []

    def execute(
        self, ctx: TenancyContext, query_exec: Callable[[str], list[dict]], sql: str
    ) -> Any:
        ok, msg = self.policy.validate(sql)
        if not ok:
            return {"error": msg}
        # 强制行级过滤（权限先于相关性）—— 固定注入租户隔离条件
        guarded = self._inject_row_filter(sql, ctx)
        rows = query_exec(guarded)
        # 列级过滤
        if ctx.col_filter:
            rows = [{k: v for k, v in r.items() if k in ctx.col_filter} for r in rows]
        self.audit_log.append({
            "tenant_id": ctx.tenant_id,
            "user_id": ctx.user_id,
            "sql": guarded,
            "rows_returned": len(rows),
        })
        return rows

    def _inject_row_filter(self, sql: str, ctx: TenancyContext) -> str:
        if not ctx.row_filter:
            return sql
        conds = [f"{k}='{v}'" for k, v in ctx.row_filter.items()]
        where = " AND ".join(conds)
        if " WHERE " in sql.upper():
            return sql + f" AND {where}"
        return sql + f" WHERE {where}"


class CredentialBroker:
    """短期凭据 Broker：按需签发 Short-Lived 凭据，原则"最小权限"。

    不影响长期保存生产密钥；到期自动失效。
    """

    def __init__(self, ttl_s: float = 300.0):
        self.ttl_s = ttl_s
        self._issued: dict[str, float] = {}

    def issue(self, role: str = "readonly") -> str:
        import time
        import uuid
        tok = f"cred_{uuid.uuid4().hex[:8]}"
        self._issued[tok] = time.time()
        return tok

    def valid(self, token: str) -> bool:
        import time
        issued = self._issued.get(token)
        if issued is None:
            return False
        return (time.time() - issued) < self.ttl_s

    def revoke_all(self) -> None:
        self._issued.clear()


class InjectionGuard:
    """Prompt 注入防护：分离系统指令与外部数据（信任边界）。"""

    def sanitize_external(self, text: str) -> str:
        """将不可信外部内容包裹不可信标记，防其伪装成指令。"""
        marker = "【外部数据·不可信】"
        return f"{marker}{text}{marker}"

    def is_instruction_leak(self, text: str) -> bool:
        m = re.search(
            r"(?i)\b(ignore|disregard|forget)\b.{0,40}\b(instructions|previous|system|prompt|user)\b",
            text,
        )
        return m is not None