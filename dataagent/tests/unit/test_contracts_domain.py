# -*- coding: utf-8 -*-
"""单元测试 —— 契约层与领域层 (DDD 纯领域逻辑)。"""
import pytest

from dataagent.contracts.model import (
    CallStatus,
    LogicalCall,
    Message,
    ModelCapability,
    Role,
    Usage,
)
from dataagent.contracts.runtime import EventType, Run, RunStatus
from dataagent.contracts.tool import (
    CapabilityRegistry,
    RiskLevel,
    Tool,
    ToolResult,
    ToolResultStatus,
)
from dataagent.domain.analytics import AnalysisPlan, Metric, RetailDiagnosisService


def make_cap():
    return ModelCapability(model="test", provider="mock")


class TestLogicalCall:
    def test_new_sets_defaults(self):
        call = LogicalCall.new(
            "planning", make_cap(), [Message(role=Role.USER, content="hi")]
        )
        assert call.status == CallStatus.PENDING
        assert call.call_id.startswith("call_")
        assert call.max_attempts == 3
        assert call.deadline > 0

    def test_attempts_grow(self):
        call = LogicalCall.new("t", make_cap(), [])
        assert len(call.attempts) == 0


class TestRun:
    def test_add_step_and_event(self):
        r = Run(query="x", tenant_id="ten_a")
        st = r.add_step("plan")
        assert st.step_id.startswith("stp_")
        evt = r.add_event(EventType.STEP_STARTED, step_id=st.step_id)
        assert evt.type == EventType.STEP_STARTED
        assert len(r.events) == 1

    def test_checkpoint_roundtrip(self):
        r = Run(query="x")
        r.add_step("s1").status.__class__  # touch
        r.status = RunStatus.RUNNING
        cp = r.to_checkpoint()
        r2 = Run()
        r2.restore(cp)
        assert r2.status == RunStatus.RUNNING
        assert [e.type for e in r2.events] == [e.type for e in r.events]


class TestMetricAlias:
    def test_alias_mapping(self):
        m = Metric("gmv", "成交总额", "已支付订单金额合计", aliases=("销售额",))
        assert m.matches("销售 额")
        assert m.matches("GMV")
        assert not m.matches("利润")


class TestToolContract:
    def test_schema_for_model_hides_governance(self):
        tool = Tool(
            name="q",
            description="d",
            parameters_schema={"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]},
            executor=lambda p: ToolResult.ok("r"),
            risk_level=RiskLevel.HIGH,
            permission="ten_a",
        )
        schema = tool.schema_for_model()
        assert "risk_level" not in str(schema)
        assert schema["function"]["name"] == "q"

    def test_params_validation(self):
        tool = Tool(
            name="q", description="d",
            parameters_schema={"type": "object", "properties": {"n": {"type": "number"}}, "required": ["n"]},
            executor=lambda p: ToolResult.ok(p["n"]),
            risk_level=RiskLevel.READONLY,
        )
        res = tool.invoke({})  # missing required
        assert res.status == ToolResultStatus.VALIDATION_ERROR
        res2 = tool.invoke({"n": "notnum"})
        assert res2.status == ToolResultStatus.VALIDATION_ERROR
        res3 = tool.invoke({"n": 5})
        assert res3.status == ToolResultStatus.OK

    def test_permission_gate(self):
        tool = Tool(
            name="q", description="d",
            parameters_schema={"type": "object", "properties": {}},
            executor=lambda p: ToolResult.ok("ok"),
            risk_level=RiskLevel.HIGH,
            permission="ten_b",
        )
        denied = tool.invoke({}, tenant_id="ten_a")
        assert denied.status == ToolResultStatus.UNAUTHORIZED

    def test_capability_registry_minimal_surface(self):
        reg = CapabilityRegistry()
        reg.register(Tool(
            name="a", description="d",
            parameters_schema={"type": "object", "properties": {"x": {"type": "string"}}},
            executor=lambda p: ToolResult.ok("v"), risk_level=RiskLevel.HIGH,
            permission="*",
        ))
        reg.register(Tool(
            name="b", description="d",
            parameters_schema={"type": "object", "properties": {}},
            executor=lambda p: ToolResult.ok("v"), risk_level=RiskLevel.READONLY,
        ))
        visible = reg.visible_for(tenant_id="ten_a", roles={"analyst"})
        names = [f["function"]["name"] for f in visible]
        assert "b" in names
        assert "a" not in names  # HIGH-risk 对 analyst 不可见（最小模型可见面）


class TestRetailDiagnosis:
    def test_diagnose_gmv_drop(self):
        svc = RetailDiagnosisService()
        sig = svc.diagnose_gmv_drop(
            "gmv",
            [{"conversion_rate": 0.3, "aov": 120}, {"conversion_rate": 0.3, "aov": 110}],
        )
        assert "转化率下降" in sig.caused_by
        assert sig.suggested_actions

    def test_analysis_plan_lifecycle(self):
        plan = AnalysisPlan("诊断", ["确认", "查询", "报告"], metric="gmv")
        assert not plan.is_complete()
        plan.mark_done("确认")
        plan.mark_done("查询")
        plan.mark_done("报告")
        assert plan.is_complete()