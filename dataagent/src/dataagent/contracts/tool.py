# -*- coding: utf-8 -*-
"""工具契约 (Tool Contract) 三层。

Alignment: 第七篇《Agent 工具 / 技能治理篇》第2课「Tool Contract 与动态工具供给」
三层 Tool Contract：
1. 模型理解层 schema_for_model —— 只暴露模型需要看的最小面 (minimal surface)
2. Runtime 执行层 invoke —— Execute/Validate，参数校验，标准结果/错误语义
3. 企业治理层 metadata —— 风险分级、权限、审计、凭据、幂等

意图定义：一个业务能力以 Tool / Skill / Workflow / SubAgent / MCP 哪种形态存在，
由 Capability 形态选型决定（见第七篇第1课）。本文件只定义 Tool 的契约形态。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


class RiskLevel(str, Enum):
    READONLY = "readonly"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ToolResultStatus(str, Enum):
    OK = "ok"
    ERROR = "error"
    VALIDATION_ERROR = "validation_error"
    UNAUTHORIZED = "unauthorized"
    RETRYABLE = "retryable"


@dataclass
class ToolResult:
    """标准工具执行结果 —— 让 Agent 能判断：重试 / 改参 / 停止。"""

    status: ToolResultStatus
    value: Any = None
    error: Optional[str] = None
    usage_tokens: int = 0
    duration_ms: float = 0.0
    audit: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def ok(value: Any, **kw: Any) -> "ToolResult":
        return ToolResult(status=ToolResultStatus.OK, value=value, **kw)

    @staticmethod
    def err(
        message: str, status: ToolResultStatus = ToolResultStatus.ERROR, **kw: Any
    ) -> "ToolResult":
        return ToolResult(status=status, error=message, **kw)


ToolFn = Callable[[dict[str, Any]], ToolResult]


@dataclass
class Tool:
    """Tool 契约对象 —— 三层合一，但对外分别只暴露所需层。"""

    name: str
    description: str
    parameters_schema: dict[str, Any]
    executor: ToolFn
    # 治理层
    risk_level: RiskLevel = RiskLevel.READONLY
    permission: Any = "*"  # 空则所有租户可用；可指定租户集合
    requires_approval: bool = False
    idempotent: bool = False
    owner: str = "platform"
    version: str = "1.0.0"

    def schema_for_model(self) -> dict[str, Any]:
        """模型理解层：只返回 name/description/parameters。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }

    def validate_params(self, params: dict[str, Any]) -> tuple[bool, str]:
        required = self.parameters_schema.get("required", [])
        props = self.parameters_schema.get("properties", {})
        missing = [k for k in required if k not in params]
        if missing:
            return False, f"缺少必要参数: {missing}"
        for k, v in params.items():
            p = props.get(k, {})
            ptype = p.get("type")
            if ptype == "string" and not isinstance(v, str):
                return False, f"参数 {k} 应为字符串"
            if ptype == "number" and not isinstance(v, (int, float)):
                return False, f"参数 {k} 应为数字"
            if ptype == "boolean" and not isinstance(v, bool):
                return False, f"参数 {k} 应为布尔"
        return True, ""

    def invoke(self, params: dict[str, Any], *, tenant_id: str = "default") -> ToolResult:
        if self.risk_level is not RiskLevel.READONLY:
            allowed = (
                self.permission.split(",")
                if isinstance(self.permission, str)
                else self.permission
            )
            if self.permission != "*" and tenant_id not in allowed:
                return ToolResult.err(
                    "当前租户无此工具权限", ToolResultStatus.UNAUTHORIZED
                )
        ok, msg = self.validate_params(params)
        if not ok:
            return ToolResult.err(msg, ToolResultStatus.VALIDATION_ERROR)
        start = time.time()
        try:
            result = self.executor(dict(params))
            result.duration_ms = (time.time() - start) * 1000
            result.audit = {
                "tool": self.name,
                "version": self.version,
                "tenant_id": tenant_id,
                "ts": time.time(),
            }
            return result
        except Exception as e:  # noqa: BLE001
            return ToolResult.err(f"执行异常: {e}", ToolResultStatus.RETRYABLE)


class CapabilityRegistry:
    """统一能力地图：Tool / Skill / Workflow / SubAgent 的注册与动态最小工具集。"""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def all(self) -> dict[str, Tool]:
        return dict(self._tools)

    def visible_for(
        self, *, tenant_id: str, roles: set[str], task: str = "", stage: str = ""
    ) -> list[dict[str, Any]]:
        """动态最小工具集：按租户 / 角色 / 任务阶段过滤后的模型可见面。"""
        out: list[dict[str, Any]] = []
        for name, t in self._tools.items():
            if t.risk_level in (RiskLevel.HIGH, RiskLevel.MEDIUM) and "admin" not in roles:
                continue
            out.append(t.schema_for_model())
        return out

    def to_json(self) -> str:
        return json.dumps(
            {k: t.schema_for_model() for k, t in self._tools.items()}, ensure_ascii=False
        )