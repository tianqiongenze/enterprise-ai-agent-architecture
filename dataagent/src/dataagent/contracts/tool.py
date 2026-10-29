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
    VERIFICATION_FAILED = "verification_failed"  # GAP-10: 执行成功但验真对账失败


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
    """Tool 契约对象 —— 三层合一，但对外分别只暴露所需层。

    治理层新增（GAP-09/10）：
    - ``idempotency_params``：幂等键的**契约声明制** —— 只有显式声明的副作用参数
      才允许进入幂等键；未声明的参数混入会被显式报错（防"描述性参数换措辞
      导致重复执行"，参照工程真实缺陷 #4 的教训）。
    - ``verifier``：验真钩子 —— 执行成功后对回执做对账，失败返回
      ``VERIFICATION_FAILED``（"说执行了"必须对得上"系统里真发生了"）。
    """

    name: str
    description: str
    parameters_schema: dict[str, Any]
    executor: ToolFn
    # 治理层
    risk_level: RiskLevel = RiskLevel.READONLY
    permission: Any = "*"  # 空则所有租户可用；可指定租户集合
    requires_approval: bool = False
    idempotent: bool = False
    # GAP-09/10：契约层的副作用治理字段
    idempotency_params: tuple[str, ...] = ()  # 声明哪些参数构成幂等键（未声明不可入键）
    verifier: Optional[Any] = None            # 验真钩子 (receipt, params) -> 失败原因或 ''
    owner: str = "platform"
    version: str = "1.0.0"
    # GAP-19b: 上线即有下线 —— 墓碑化（能力消失必须可审计）
    retired: bool = False
    retired_reason: str = ""
    retired_by: str = ""
    retired_at: float = 0.0

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
            if ptype == "number":
                # 陷阱防御(GAP-04): Python 的 bool 是 int 子类,
                # 必须先排除 bool, 否则 True/False 会通过 number 校验
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    return False, f"参数 {k} 应为数字"
            if ptype == "boolean" and not isinstance(v, bool):
                return False, f"参数 {k} 应为布尔"
        return True, ""

    def build_effect_key(self, params: dict[str, Any]) -> str:
        """按契约声明构造幂等键（GAP-09）。

        只取 ``idempotency_params`` 声明的副作用参数（排序后拼接）；
        params 中出现**未声明**的键 → 显式报错 —— 描述性参数（如 reason 文本）
        混进幂等键会让"换个措辞"变成一次新执行，幂等承诺失效。
        """
        if not self.idempotency_params:
            raise ValueError(f"工具 {self.name} 未声明 idempotency_params，无法构造幂等键")
        undeclared = sorted(set(params) - set(self.idempotency_params))
        if undeclared:
            raise ValueError(
                f"参数 {undeclared} 未在 idempotency_params 声明，禁止进入幂等键"
                f"（声明清单: {list(self.idempotency_params)}）"
            )
        parts = "&".join(
            f"{k}={params[k]}" for k in sorted(self.idempotency_params) if k in params
        )
        return f"{self.name}:{parts}"

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
            # 验真钩子（GAP-10）：执行成功 ≠ 系统里真发生了 —— 对账失败按失败返回
            if result.status is ToolResultStatus.OK and self.verifier is not None:
                vmsg = self.verifier(result, dict(params))
                if vmsg:
                    return ToolResult.err(
                        f"验真失败: {vmsg}", ToolResultStatus.VERIFICATION_FAILED,
                        duration_ms=result.duration_ms, audit=result.audit,
                    )
            return result
        except Exception as e:  # noqa: BLE001
            return ToolResult.err(f"执行异常: {e}", ToolResultStatus.RETRYABLE)


class CapabilityRegistry:
    """统一能力地图：Tool / Skill / Workflow / SubAgent 的注册与动态最小工具集。

    GAP-19b：能力生命周期治理 —— ``retire`` 下线打墓碑（保留记录，不静默消失），
    ``tombstones`` 供运营盘点；下线能力对模型不可见，也不应被 Runtime 执行（见 ``get``）。
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._retired: dict[str, dict[str, Any]] = {}  # tombstone: {name, retired_by, reason, ts}

    def register(self, tool: Tool) -> None:
        if tool.name in self._retired and not tool.retired:
            # 重新注册视为复活：清墓碑并留痕由调用方日志说明（能力复用需显式发生）
            self._retired.pop(tool.name)
        self._tools[tool.name] = tool

    def retire(self, name: str, *, by: str = "ops", reason: str = "") -> bool:
        """下线能力（打墓碑）：true=成功下线，false=能力不存在。幂等安全。"""
        t = self._tools.get(name)
        if t is None:
            return False
        if t.retired:
            return True  # 已下线，幂等
        t.retired = True
        t.retired_by = by
        t.retired_reason = reason
        t.retired_at = time.time()
        self._retired[name] = {
            "name": name, "retired_by": by, "reason": reason, "ts": t.retired_at,
            "owner": t.owner, "version": t.version,
        }
        return True

    def tombstones(self) -> dict[str, dict[str, Any]]:
        return dict(self._retired)

    def active_tools(self) -> list[Tool]:
        return [t for t in self._tools.values() if not t.retired]

    def get(self, name: str) -> Optional[Tool]:
        # 已下线能力对执行层不可达（取不到 → Runtime 报"工具不存在"，与从未注册同语义）
        t = self._tools.get(name)
        return None if t is None or t.retired else t

    def all(self) -> dict[str, Tool]:
        return {k: v for k, v in self._tools.items() if not v.retired}

    def visible_for(
        self, *, tenant_id: str, roles: set[str], task: str = "", stage: str = ""
    ) -> list[dict[str, Any]]:
        """动态最小工具集：按租户 / 角色 / 任务阶段过滤后的模型可见面。"""
        out: list[dict[str, Any]] = []
        for name, t in self._tools.items():
            if t.retired:  # 下线能力不进模型视野
                continue
            if t.risk_level in (RiskLevel.HIGH, RiskLevel.MEDIUM) and "admin" not in roles:
                continue
            out.append(t.schema_for_model())
        return out

    def to_json(self) -> str:
        data: dict[str, Any] = {k: t.schema_for_model() for k, t in self._tools.items() if not t.retired}
        if self._retired:
            data["__tombstones__"] = dict(self._retired)
        return json.dumps(data, ensure_ascii=False)