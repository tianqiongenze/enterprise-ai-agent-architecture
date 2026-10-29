# -*- coding: utf-8 -*-
"""分支补全测试（GAP-02）：把"正常路径永远走不到"的分支变成被钉住的行。

覆盖目标（按覆盖率报告的缺失分布，逐项对应）：
- __main__（CLI 形态）/ workflow（审批否决路径/幂等查询/回执构造）
- fake_client（结构化处理器/工具调用决策/stream/默认 schema 回退）
- eval_ops（LLM Grader 占位/ReleaseEVolution/空 Dataset 口径）
- skill / sandbox / analytics / tools / assembler / memory / harness 治理件
"""
import json

import pytest

from dataagent.adapters.llm.fake_client import FakeLlmClient
from dataagent.contracts.model import LogicalCall, Message, ModelCapability, Role
from dataagent.contracts.runtime import Run, RunStatus
from dataagent.contracts.tool import RiskLevel, Tool, ToolResult, ToolResultStatus
from dataagent.domain.analytics import (
    AnalysisPlan,
    AnomalySignature,
    RetailDiagnosisService,
    Tenant,
)
from dataagent.infra.context.assembler import (
    ContextAssembler,
    ContextContract,
    ContextItem,
    ContextProvider,
    Provenance,
    render_prompt_template,
    simple_provider,
)
from dataagent.infra.gateway.llm_runtime import CallStats, ModelRegistry
from dataagent.infra.gateway.tools import TenantDataLake, build_dataagent_toolchain
from dataagent.infra.memory.memory import (
    InMemoryMemoryStore,
    Memory,
    MemoryPolicyEngine,
    MemoryRecallEvaluator,
    MemoryScope,
    MemoryWritePipeline,
)
from dataagent.infra.metrics.eval_ops import (
    BatchEvalRunner,
    EvalReport,
    ReleaseEVolution,
    code_grader,
    llm_grader,
    snapshot_fixture,
)
from dataagent.infra.runtime.harness import AutonomyBudget, StopCondition, Verifier
from dataagent.infra.runtime.workflow import (
    DurableWorkflowExecutor,
    HumanApprovalGate,
    IdempotencyStore,
    InMemoryApprovalPort,
    InMemoryRunStore,
    WorkflowDefinition,
    WorkflowNode,
    build_approval_action,
)
from dataagent.infra.sandbox.executor import NetworkPolicy, PythonSandbox
from dataagent.infra.security.guards import CredentialBroker
from dataagent.infra.skills.skill import Skill, SkillRegistry, build_anomaly_skill


class TestCliMain:
    def test_help_exits_zero(self, capsys):
        from dataagent.__main__ import main
        assert main(["--help"]) == 0
        assert "用法" in capsys.readouterr().out

    def test_query_runs_offline(self, capsys):
        from dataagent.__main__ import main
        rc = main(["华东区 GMV 下滑诊断"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "状态=succeeded" in out and "Run Timeline" in out


class TestWorkflowBranches:
    def _executor(self, auto: bool = True):
        port = InMemoryApprovalPort(auto_approve=auto)
        ex = DurableWorkflowExecutor(
            store=InMemoryRunStore(), approval=HumanApprovalGate(port),
            idem=IdempotencyStore(), harness_runner=None,
        )
        return ex, port

    def test_pending_gate_interrupts_instead_of_succeeding(self):
        """审批未决（无决议）：流程必须 interrupt，不得带挂起状态走向终态。

        这是由状态机拒绝 waiting_approval→succeeded 暴露的真实语义缺陷：
        旧实现会让"审批还没人管"的流程继续跑完并标记成功。
        """
        from dataagent.contracts.runtime import ApprovalPendingError
        ex, port = self._executor(auto=False)
        wf = WorkflowDefinition("x", nodes=[WorkflowNode("g", "human_gate", approval_action="a")])
        run = Run(query="x")
        with pytest.raises(ApprovalPendingError):
            ex.execute(wf, run)
        assert run.status.value == "waiting_approval"          # 挂起等待决议
        assert run.steps[-1].status.value == "waiting_approval"
        # 决议后带 pre_approved 恢复 → 正常到终态
        from dataagent.contracts.runtime import ApprovalDecision, ApprovalRequest
        req = ApprovalRequest(request_id=run.steps[-1].output.get("request_id") or "apr_x",
                              run_id=run.run_id, action="a", params={})
        port.request(req)
        port.resolve(req.request_id, ApprovalDecision.APPROVED, by="审批人")
        run2 = ex.execute(wf, run, pre_approved={"a": {"decision": "approved", "by": "审批人"}})
        assert run2.status.value == "succeeded"

    def test_idempotency_store_has_query(self):
        idem = IdempotencyStore()
        assert idem.has("k1") is False
        assert idem.try_mark("k1") is True
        assert idem.has("k1") is True
        assert idem.try_mark("k1") is False

    def test_build_approval_action_receipt(self):
        receipt = build_approval_action(Run(query="x"), {"region": "华东"})
        assert receipt["action"] == "side_effect_executed"
        assert receipt["params"] == {"region": "华东"}

    def test_run_store_missing_key_raises(self):
        store = InMemoryRunStore()
        with pytest.raises(KeyError):
            store.load("nope")

    def test_approval_gate_request_and_status(self):
        port = InMemoryApprovalPort(auto_approve=False)
        gate = HumanApprovalGate(port)
        from dataagent.contracts.runtime import ApprovalRequest
        rid = gate.request("run1", "adjust_budget", {"amount": 1})
        assert gate.is_approved(rid) is False


class TestFakeClientBranches:
    def test_structured_handler_override(self):
        c = FakeLlmClient(structured_handler=lambda msgs, n: {"ok": 1})
        cap = ModelCapability(model="m")
        call = LogicalCall.new(task="t", capability=cap, messages=[Message(role=Role.USER, content="x")])
        res = c.complete(cap, call.messages, structured=dict)
        assert res.structured == {"ok": 1}

    def test_tool_call_decision_branch(self):
        c = FakeLlmClient()
        cap = ModelCapability(model="m")
        msgs = [Message(role=Role.USER, content='调用工具:query_metric|{"tenant_id": "ten_a"}')]
        res = c.complete(cap, msgs)
        assert res.tool_calls and res.tool_calls[0].name == "query_metric"
        assert res.tool_calls[0].arguments == {"tenant_id": "ten_a"}

    def test_stream_yields_text(self):
        c = FakeLlmClient(handler=lambda msgs, n: "流式输出")
        cap = ModelCapability(model="m")
        assert "".join(c.stream(cap, [Message(role=Role.USER, content="x")])) == "流式输出"

    def test_default_structured_fills_required_fields(self):
        class FakeSchema:
            @staticmethod
            def model_json_schema():
                return {"required": ["steps", "conclusion", "evidence"]}
        c = FakeLlmClient()
        cap = ModelCapability(model="m")
        msgs = [Message(role=Role.USER, content="请给结论")]
        data = c._default_structured(FakeSchema, msgs)
        assert data["steps"] == ["查询数据", "诊断原因"]
        assert data["conclusion"]


class TestEvalOpsBranches:
    def test_llm_grader_placeholder_scores_pass(self):
        from dataagent.infra.metrics.eval_ops import fake_judge
        g = llm_grader(fake_judge)
        res = g.grade(Run(query="x"), {})
        assert res.passed and "通过" in res.detail

    def test_llm_grader_judge_injection(self):
        """依赖方向修正后的新语义：judge 可注入（infra 不再耦合 adapters）。"""
        g = llm_grader(lambda run, ref: "质量不达标")
        res = g.grade(Run(query="x"), {})
        assert not res.passed and res.score == 0.5  # 部分达成: 有判断但未通过

    def test_release_evolution_canary_rollback_promote_guard(self):
        rel = ReleaseEVolution()
        rel.canary(10)
        rel.promote("v1")
        msg = rel.rollback("v0")
        assert "Kill Switch" in msg
        rel.promote("v2")  # 紧急态下晋升被拒
        assert rel.released_versions == ["v1"]

    def test_empty_dataset_scorecard_is_zero(self):
        report = BatchEvalRunner([code_grader(lambda r: True)]).evaluate([])
        assert report.scorecard == {}          # 无 case 无维度均值(诚实口径, 不假装 0 分)
        assert report.mean_outcome == 0.0      # code 维缺失按 0.0 兜底

    def test_report_summary_and_mean(self):
        report = EvalReport(cases=[{"code": 1.0}], scorecard={"code": 1.0}, max_scores={"code": 20})
        assert "code: 1.0 / 20" in report.summary()
        assert report.mean_outcome == 1.0

    def test_snapshot_fixture_deterministic_fingerprint(self):
        f1 = snapshot_fixture(model="m", prompt_version="p", context_version="c", tool_set="t", tenant="ten_a")
        f2 = snapshot_fixture(model="m", prompt_version="p", context_version="c", tool_set="t", tenant="ten_a")
        f3 = snapshot_fixture(model="m", prompt_version="p2", context_version="c", tool_set="t", tenant="ten_a")
        assert f1["fingerprint"] == f2["fingerprint"] != f3["fingerprint"]


class TestSkillBranches:
    def test_progressive_load_no_match_returns_empty(self):
        reg = SkillRegistry()
        build_anomaly_skill(reg)
        assert reg.progressive_load("reporting") == []

    def test_default_validator_checks_completion_criteria(self):
        s = Skill(name="x", mission="m", completion_criteria=["a", "b"])
        ok, msg = s.validate({"a": 1})
        assert not ok and "b" in msg
        ok, msg = s.validate({"a": 1, "b": 2})
        assert ok

    def test_strict_evidence_false_allows_unverified(self):
        reg = SkillRegistry()
        skill = build_anomaly_skill(reg, strict_evidence=False)
        ok, msg = skill.validate({"metric_confirmed": True, "evidence": ["e1"]})
        assert ok and msg == "ok"

    def test_mission_boundary_in_fragment(self):
        reg = SkillRegistry()
        skill = build_anomaly_skill(reg)
        assert "经营异常诊断" in skill.prompt_fragment


class TestSandboxBranches:
    def test_analyze_computes_mean(self):
        sb = PythonSandbox()
        out = sb.analyze("avg", {"a": 2, "b": 4})
        assert out["computed_mean"] == 3.0 and out["input_size"] == 2

    def test_analyze_empty_data(self):
        assert PythonSandbox().analyze("avg", {})["computed_mean"] == 0.0

    def test_network_policy_default_deny_external(self):
        np = NetworkPolicy()
        assert np.can_connect("localhost") is True
        assert np.can_connect("evil.example.com") is False
        assert NetworkPolicy(allow=("api.internal",)).can_connect("api.internal") is True


class TestAnalyticsBranches:
    def test_tenant_permission_matrix(self):
        admin = Tenant(tenant_id="t", roles={"admin"})
        assert admin.can("adjust_budget") and admin.can("anything_else")
        assert not Tenant(tenant_id="t", roles={"viewer"}).can("query") is False  # 查询人人可

    def test_diagnosis_empty_rows(self):
        sig = RetailDiagnosisService().diagnose_gmv_drop("gmv", [])
        assert sig.reason == "缺少数据" and sig.evidence_keys == ["no_data"]

    def test_format_report_with_and_without_actions(self):
        svc = RetailDiagnosisService()
        plain = svc.format_for_report(AnomalySignature(caused_by="转化率下降", reason="r"))
        assert "经营异常诊断结论" in plain and "建议" not in plain
        rich = svc.format_for_report(AnomalySignature(caused_by="x", reason="r", suggested_actions=["做A", "做B"]))
        assert "做A；做B" in rich

    def test_analysis_plan_lifecycle(self):
        plan = AnalysisPlan(goal="g", steps=["s1", "s2"])
        assert plan.remaining == ["s1", "s2"] and not plan.is_complete()
        plan.mark_done("s1")
        assert plan.remaining == ["s2"]
        plan.mark_done("s2")
        assert plan.is_complete()
        assert AnalysisPlan(goal="g", steps=[]).is_complete()


class TestToolsBranches:
    def test_lake_query_rejects_non_orders_table(self):
        lake = TenantDataLake()
        with pytest.raises(ValueError, match="orders"):
            lake.query("ten_a", "SELECT * FROM secret_table")

    def test_lake_query_region_filter_and_empty_tenant(self):
        lake = TenantDataLake()
        lake.set_orders("ten_a", [{"region": "华东", "amount": 1}, {"region": "华南", "amount": 2}])
        rows = lake.query("ten_a", "SELECT * FROM orders WHERE region='华东'")
        assert len(rows) == 1 and rows[0]["region"] == "华东"
        assert lake.compute_metrics("ghost")["gmv"] == 0.0

    def test_query_orders_with_region_and_row_cap(self):
        lake = TenantDataLake()
        lake.set_orders("ten_a", [{"region": "华东", "amount": i} for i in range(300)])
        reg = build_dataagent_toolchain(lake)
        res = reg.get("query_orders").invoke(
            {"tenant_id": "ten_a", "sql": "SELECT * FROM orders", "region": "华东"},
            tenant_id="ten_a")
        assert res.value["count"] == 300 and len(res.value["rows"]) == 200  # 截断上限

    def test_python_analyze_without_data(self):
        lake = TenantDataLake()
        reg = build_dataagent_toolchain(lake)
        res = reg.get("python_analyze").invoke({"metric": "gmv"}, tenant_id="ten_a")
        assert res.status is ToolResultStatus.OK and "无输入数据" in res.value["note"]

    def test_create_ticket_idempotent_key_receipt(self):
        lake = TenantDataLake()
        reg = build_dataagent_toolchain(lake)
        res = reg.get("create_ticket").invoke({"title": "t", "idempotency_key": "abc"}, tenant_id="ten_a")
        assert res.value["status"] == "created" and res.value["ticket_id"].startswith("TK-")

    def test_adjust_budget_receipt(self):
        lake = TenantDataLake()
        reg = build_dataagent_toolchain(lake)
        res = reg.get("adjust_budget").invoke(
            {"region": "华东", "amount": 100, "idempotency_key": "k"}, tenant_id="ten_a")
        assert res.value == {"region": "华东", "delta": 100, "status": "applied"}


class TestAssemblerBranches:
    def test_render_prompt_template_with_header(self):
        a = ContextAssembler()
        a.register(simple_provider("tenant_identity", "租户身份：零售商家",
                                   provenance=Provenance.TENANT_ATTR, priority=90))
        a.register(simple_provider("kb", "业务知识条目", provenance=Provenance.BUSINESS_KNOWLEDGE))
        s = a.assemble()
        text = render_prompt_template(s, header="## 任务")
        assert text.startswith("## 任务") and "系统规则与租户信息" in text and "决策上下文" in text
        assert "[kb] 业务知识条目" in text

    def test_role_mismatch_filtered(self):
        a = ContextAssembler()
        # tenant_id="*" 表示租户无关条目(系统级), 否则会先撞租户过滤而非角色过滤
        a.register(simple_provider("secret", "管理员专属", tenant_id="*", role_mask=("admin",)))
        s = a.assemble(tenant_id="t", roles={"analyst"})
        assert [k for k, r in s.filtered if r == "role_mismatch"] == ["secret"]

    def test_hard_filter_hook(self):
        a = ContextAssembler()
        a.register(simple_provider("x", "内容"))
        s = a.assemble(hard_filter=lambda it: (False, "custom_block"))
        assert s.filtered and s.filtered[0][1] == "custom_block"

    def test_contract_blocked_and_sufficiency(self):
        a = ContextAssembler()
        a.register(simple_provider("blocked_key", "禁项内容"))
        s = a.assemble()
        c = ContextContract("x", required=("missing_req",), blocked=("blocked_key",))
        assert c.required_intersection(s) == ["missing_req"]
        assert c.violates_blocked(s) == ["blocked_key"]
        assert c.sufficiency_ok(s) is False


class TestMemoryBranches:
    def test_task_scope_matches_everything(self):
        m = Memory(scope=MemoryScope.TASK, tenant_id="ten_a", owner="u1", key="k", content="任务级")
        assert m.matches_scope("any", "any") is True

    def test_memory_expiry(self):
        m = Memory(scope=MemoryScope.USER, tenant_id="t", owner="u", key="k", content="c", ttl_s=0.01)
        import time as _t
        _t.sleep(0.02)
        assert m.expired is True

    def test_write_needs_confirm_and_deny_short(self):
        store = InMemoryMemoryStore()
        pipe = MemoryWritePipeline(store, MemoryPolicyEngine())
        ok, msg, _ = pipe.write(tenant_id="t", owner="u", key="k",
                                content="全租户级备注", scope=MemoryScope.TENANT)
        assert not ok and "需人工确认" in msg
        ok, msg, _ = pipe.write(tenant_id="t", owner="u", key="k2", content="短")
        assert not ok and "过短" in msg

    def test_recall_empty_eval_cases_guard(self):
        ev = MemoryRecallEvaluator(InMemoryMemoryStore())
        report = ev.evaluate([])
        assert report["cases"] == 0 and report["passed"] is False


class TestHarnessGovernancePieces:
    def test_budget_spend_tool_call(self):
        b = AutonomyBudget(max_steps=9, max_tokens=9, max_tool_calls=1)
        b.spend_tool_call()
        assert b.can_continue() is False  # 工具调用触顶

    def test_stop_condition_counts_conclusions(self):
        sc = StopCondition(max_conclusions=2)
        assert sc.should_stop("plan", True) is False
        assert sc.should_stop("conclusion", True) is False
        assert sc.should_stop("conclusion", True) is True
        assert sc.should_stop("conclusion", False) is False  # 验证未过不停

    def test_verifier_runs_checks_in_order(self):
        v = Verifier(checks=[lambda ctx: "" , lambda ctx: "第二条失败"])
        ok, msg = v.run({})
        assert not ok and msg == "第二条失败"


class TestLlmRuntimeMisc:
    def test_callstats_estimated_cost_demo_scale(self):
        s = CallStats(input_tokens=1000, output_tokens=1000)
        assert s.estimated_cost == pytest.approx(0.4)

    def test_registry_alias_and_missing(self):
        reg = ModelRegistry()
        reg.register(ModelCapability(model="real"))
        reg.alias("logic", "real")
        assert reg.has("logic") and not reg.has("ghost")
        with pytest.raises(KeyError):
            reg.resolve("ghost")

    def test_tool_to_json_serializable(self):
        lake = TenantDataLake()
        reg = build_dataagent_toolchain(lake)
        data = json.loads(reg.to_json())
        assert set(data) == {"query_metric", "query_orders", "python_analyze", "create_ticket", "adjust_budget"}


class TestGuardsMisc:
    def test_credential_revoke_all(self):
        cb = CredentialBroker(ttl_s=999)
        tok = cb.issue()
        assert cb.valid(tok)
        cb.revoke_all()
        assert not cb.valid(tok)
