# -*- coding: utf-8 -*-
"""DataAgent 工具链 (第七篇) —— 企业级只读工具 + 有副作用工具。

将"指标查询、经营数据查询、Python 分析、报告生成"封装为企业级只读工具，
"创建工单、调整预算"封装为需审批的高风险 Action 工具。
数据源实际来自内存模拟 (TenantDataLake)，保证离线可运行、可测试。
"""
from __future__ import annotations

import hashlib
from typing import Any, Optional

from ...contracts.tool import (
    CapabilityRegistry,
    RiskLevel,
    Tool,
    ToolResult,
    ToolResultStatus,
)


class TenantDataLake:
    """多租户数据湖：按租户隔离的模拟订单明细 + 指标计算。"""

    def __init__(self) -> None:
        self._tables: dict[str, dict[str, list[dict]]] = {}

    def set_orders(self, tenant: str, rows: list[dict]) -> None:
        self._tables.setdefault(tenant, {})["orders"] = rows

    def query(self, tenant: str, sql: str) -> list[dict]:
        if "FROM orders" not in sql and "orders" not in sql:
            raise ValueError("只允许查询 orders 表")
        rows = self._tables.get(tenant, {}).get("orders", [])
        # 极简 SQL 子集：支持 WHERE region=xxx (演示用，非真 SQL 引擎)
        import re
        m = re.search(r"(?:region|area|来源)\s*=\s*'([^']+)'", sql, re.I)
        if m:
            val = m.group(1)
            rows = [r for r in rows if r.get("region") == val]
        return rows

    def compute_metrics(self, tenant: str) -> dict[str, float]:
        rows = self._tables.get(tenant, {}).get("orders", [])
        if not rows:
            return {"gmv": 0.0, "order_count": 0.0, "aov": 0.0, "conversion_rate": 0.0, "refund_rate": 0.0}
        total = sum(float(r.get("amount", 0)) for r in rows)
        count = len(rows)
        refunds = sum(1 for r in rows if r.get("refunded"))
        return {
            "gmv": round(total, 2),
            "order_count": float(count),
            "aov": round(total / count, 2) if count else 0.0,
            "conversion_rate": round(sum(float(r.get("conversion_rate", 0.5)) for r in rows) / count, 4),
            "refund_rate": round(refunds / count, 4) if count else 0.0,
        }


def build_dataagent_toolchain(
    lake: TenantDataLake,
    registry: Optional[CapabilityRegistry] = None,
) -> CapabilityRegistry:
    """装配 DataAgent 的全部工具能力地图。"""
    reg = registry or CapabilityRegistry()

    def query_metric(tenant: str) -> ToolResult:
        metrics = lake.compute_metrics(tenant)
        return ToolResult.ok(metrics)

    def query_orders(params: dict) -> ToolResult:
        sql = params.get("sql", "")
        region = params.get("region")
        rows = lake.query(params["tenant_id"], sql)
        if region:
            rows = [r for r in rows if r.get("region") == region]
        return ToolResult.ok({"count": len(rows), "rows": rows[:200]})

    def python_analyze(params: dict) -> ToolResult:
        code = params.get("code", "")
        data = params.get("data")
        # 演示性 Python 分析：这里执行受限的统计逻辑，不 eval 任意代码
        metric = params.get("metric", "gmv")
        if data and metric in data:
            val = data[metric]
            delta = params.get("vs", 0)
            trend = "上升" if (val or 0) >= delta else "下降"
            return ToolResult.ok({
                "metric": metric,
                "value": val,
                "trend": trend,
                "note": "（沙箱 Python 分析已执行：均值/趋势)数据",
            })
        return ToolResult.ok({"note": "无输入数据，跳过分析"})

    def create_ticket(params: dict) -> ToolResult:
        # 高风险副作用：写"工单系统"；幂等键去重
        return ToolResult.ok({"ticket_id": f"TK-{hashlib.md5(params.get('idempotency_key','').encode()).hexdigest()[:8]}", "status": "created"})

    def adjust_budget(params: dict) -> ToolResult:
        region = params["region"]
        amount = params["amount"]
        return ToolResult.ok({"region": region, "delta": amount, "status": "applied"})

    reg.register(Tool(
        name="query_metric",
        description="查询某租户的经营核心指标（GMV/订单数/客单价/转化率/退款率）",
        parameters_schema={
            "type": "object",
            "properties": {
                "tenant_id": {"type": "string"},
                "metric": {"type": "string", "description": "gmv/order_count/aov/conversion_rate/refund_rate"},
            },
            "required": ["tenant_id"],
        },
        executor=lambda params: query_metric(params.get("tenant_id", "ten_a")),
        risk_level=RiskLevel.READONLY,
    ))
    reg.register(Tool(
        name="query_orders",
        description="按 SQL WHERE 条件查询订单明细（仅 orders 表，行级权限在网关层注入）",
        parameters_schema={
            "type": "object",
            "properties": {
                "tenant_id": {"type": "string"},
                "sql": {"type": "string", "description": "SQL WHERE 片段，例如 region='华东'"},
                "region": {"type": "string"},
            },
            "required": ["tenant_id"],
        },
        executor=lambda params: query_orders({**params, "tenant_id": params.get("tenant_id", "ten_a")}),
        risk_level=RiskLevel.READONLY,
    ))
    reg.register(Tool(
        name="python_analyze",
        description="在云端 Python 沙箱中对查询结果做统计分析与图表生成准备",
        parameters_schema={
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "data": {"type": "object"},
                "metric": {"type": "string"},
                "vs": {"type": "number"},
            },
            "required": ["metric"],
        },
        executor=python_analyze,
        risk_level=RiskLevel.READONLY,
    ))
    reg.register(Tool(
        name="create_ticket",
        description="创建一条经营动作工单（高风险，需人工审批）",
        parameters_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "tenant_id": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["title", "idempotency_key"],
        },
        executor=create_ticket,
        risk_level=RiskLevel.HIGH,
        permission="*",
        requires_approval=True,
        idempotent=True,
    ))
    reg.register(Tool(
        name="adjust_budget",
        description="调整某区域营销预算（高风险副作用，需人工审批）",
        parameters_schema={
            "type": "object",
            "properties": {
                "region": {"type": "string"},
                "amount": {"type": "number"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["region", "amount", "idempotency_key"],
        },
        executor=adjust_budget,
        risk_level=RiskLevel.HIGH,
        requires_approval=True,
        idempotent=True,
    ))
    return reg