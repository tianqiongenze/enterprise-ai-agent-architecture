# -*- coding: utf-8 -*-
"""领域层：多租户零售经营分析与决策 DataAgent 的领域模型 (DDD 核心)。

Aggregate: Metric, Tenant, Indicator, AnalysisPlan
领域服务：MetricRegistry, 指标口径校验、异常诊断、零售退单
无基础设施依赖 —— 纯领域逻辑，可单测。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Protocol


class MetricLevel(str):
    RESTAURANT_USER = "user"
    METRIC = "metric"
    TABLE = "table"


@dataclass(frozen=True)
class Metric:
    """一个标准经营指标 (Metric) —— 它是对指标的权威定义，不是一条数据。"""

    name: str            # 唯一标识，如 "gmv", "order_count"
    display_name_zh: str # 中文名，如 "成交总额"
    formula: str         # 计算口径，如 "已支付订单金额合计"
    aliases: tuple[str, ...] = ()
    dimension: str = "amount"   # amount / count / rate / stock
    refresh_policy: str = "daily"

    def matches(self, expr: str) -> bool:
        """把自然语言映射回指标（别名解析）。"""
        expr_n = expr.strip().lower().replace(" ", "")
        names = [self.name.lower(), self.display_name_zh] + list(self.aliases)
        return any(n.replace(" ", "").lower() == expr_n for n in names)


class MetricRegistry(Protocol):
    def get(self, name: str) -> Optional[Metric]: ...
    def all(self) -> list[Metric]: ...
    def register(self, metric: Metric) -> None: ...


@dataclass
class Tenant:
    """多租户：租户身份、角色、行列权限。

    权限模型：
    - data_sources: 该租户可访问的数据源 id 列表
    - roles: 用户角色（决定能否触发副作用 / 审批）
    - row_filter: 行级过滤 (如 region=华东)
    - col_filter: 列级过滤 (可看字段白名单)
    """

    tenant_id: str
    name: str = ""
    data_sources: tuple[str, ...] = ()
    roles: set[str] = field(default_factory=lambda: {"analyst"})
    row_filter: Optional[dict[str, str]] = None
    col_filter: Optional[tuple[str, ...]] = None

    def can(self, action: str) -> bool:
        """风险动作权限判断。"""
        high = {"approve", "adjust_budget", "create_ticket"}
        if action in high:
            return "admin" in self.roles or "approver" in self.roles
        if action in {"query", "read"}:
            return True
        return "admin" in self.roles


@dataclass
class AnomalySignature:
    """异常诊断的领域结果。"""

    caused_by: str = ""
    reason: str = ""
    impact_pct: Optional[float] = None
    evidence_keys: list[str] = field(default_factory=list)
    suggested_actions: list[str] = field(default_factory=list)


class RetailDiagnosisService:
    """领域服务：基于订单明细对经营指标做异常归因。"""

    def diagnose_gmv_drop(self, metric: str, rows: list[dict]) -> AnomalySignature:
        """对 GMV 下滑做"归因树"式诊断。

        输入 rows 为按 (转化率, 客单价) 聚合或订单明细行。
        """
        if not rows:
            return AnomalySignature(
                reason="缺少数据", evidence_keys=["no_data"]
            )
        conv_sum = sum(float(r.get("conversion_rate", 0.5)) for r in rows)
        aov_sum = sum(float(r.get("aov", 200)) for r in rows)
        n = len(rows)
        conv_avg = conv_sum / n if n else 0.0
        aov_avg = aov_sum / n if n else 0.0
        caused = []
        if conv_avg < 0.45:
            caused.append("转化率下降")
        if aov_avg < 180:
            caused.append("客单价下降")
        if not caused:
            caused.append("流量下降")
        actions = []
        if "转化率下降" in caused:
            actions.append("检查促销与落地页，提升转化")
        if "客单价下降" in caused:
            actions.append("调整组合定价，提升客单价")
        return AnomalySignature(
            caused_by=";".join(caused),
            reason=f"综合转化率均值 {conv_avg:.2f}、客单价均值 {aov_avg:.0f}",
            impact_pct=round((1 - conv_avg * aov_avg / 100) * 100, 2),
            evidence_keys=[f"row_{i}" for i in range(n)],
            suggested_actions=actions,
        )

    def format_for_report(self, sig: AnomalySignature) -> str:
        lines = [
            "经营异常诊断结论：",
            f"- 触发因子：{sig.caused_by or '未明确'}",
            f"- 说明：{sig.reason}",
            f"- 潜在影响：{sig.impact_pct}%",
        ]
        if sig.suggested_actions:
            lines.append("- 建议：" + "；".join(sig.suggested_actions))
        return "\n".join(lines)


class TenantTenantRepository(Protocol):
    def get(self, tenant_id: str) -> Tenant: ...


class AnalysisPlan:
    """一个经营分析的领域计划：多步骤。"""

    def __init__(self, goal: str, steps: list[str], metric: Optional[str] = None):
        self.goal = goal
        self.steps = steps
        self.metric = metric
        self.completed: set[str] = set()

    def mark_done(self, step: str) -> None:
        self.completed.add(step)

    @property
    def remaining(self) -> list[str]:
        return [s for s in self.steps if s not in self.completed]

    def is_complete(self) -> bool:
        return not self.remaining or not self.steps