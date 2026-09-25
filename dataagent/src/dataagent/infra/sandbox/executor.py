# -*- coding: utf-8 -*-
"""云端 Python 沙箱 (第七篇第3课 Action Runtime) + 执行隔离。

只读沙箱：对 python_analyze 提供受限统计执行，绝不 eval 任意代码。
"""
from __future__ import annotations

from typing import Any, Optional


class PythonSandbox:
    """受限沙箱执行环境 —— 仅暴露安全的统计函数，隔离任意代码执行。"""

    def analyze(self, code: str, data: dict[str, Any]) -> dict[str, Any]:
        # 演示实现：在真实企业中对应"云端 Python Sandbox 隔离执行 + 资源限额 + 审计"
        avg = sum(data.values()) / len(data) if data else 0.0
        return {
            "sandbox": "pystd-v1",
            "input_size": len(data),
            "computed_mean": round(avg, 4),
            "ast_node_count": 0,  # 真实实现会对 AST 做白名单
        }


class NetworkPolicy:
    """沙箱网络策略：默认禁止外联，防止数据外泄。"""

    def __init__(self, allow: tuple[str, ...] = ()):
        self.allow = allow

    def can_connect(self, host: str) -> bool:
        if host in ("", "localhost", "127.0.0.1"):
            return True
        return host in self.allow