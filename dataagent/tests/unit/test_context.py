# -*- coding: utf-8 -*-
"""单元测试 —— 上下文治理 (第六篇)：ContextSchema/装配/契约/充分性/权限/预算。"""
from dataagent.infra.context.assembler import (
    ContextAssembler,
    ContextContract,
    ContextItem,
    ContextProvider,
    Provenance,
    TrustLevel,
    render_prompt_template,
)


def item(key, content, **kw):
    return ContextItem(key=key, content=content, **kw)


class TestContextSchema:
    def test_fields(self):
        it = item("k", "内容", provenance=Provenance.BUSINESS_KNOWLEDGE, trust=TrustLevel.TRUSTED)
        assert it.provenance.value == "business_knowledge"
        assert not it.expired  # ttl 未设

    def test_expiry(self):
        import time
        it = item("k", "v", ttl_s=0.001)
        time.sleep(0.01)
        assert it.expired


class TestAssembler:
    def test_hard_filter_priority(self):
        a = ContextAssembler(token_budget=5000)
        a.register(ContextProvider("secret", lambda: item("secret", "跨租户机密", tenant_id="ten_b"), priority=100))
        a.register(ContextProvider("ok", lambda: item("ok", "允许", tenant_id="*"), priority=1))
        sl = a.assemble(tenant_id="ten_a", roles={"analyst"})
        keys = {it.key for it in sl.items}
        assert "ok" in keys
        assert "secret" not in keys
        # 过滤原因必须被记录
        reasons = [f for _, f in sl.filtered]
        assert any("tenant_mismatch" in r for r in reasons)

    def test_role_filter(self):
        a = ContextAssembler()
        a.register(ContextProvider("admin_only", lambda: item("admin_only", "x", role_mask=("admin",)), priority=50))
        sl = a.assemble(roles={"analyst"})
        assert "admin_only" not in {i.key for i in sl.items}

    def test_budget_partition_and_total(self):
        a = ContextAssembler(token_budget=100, budget_partitions={"business_knowledge": 40})
        for i in range(50):
            a.register(ContextProvider(f"p{i}", lambda i=i: item(f"k{i}", "长内容" * 40), priority=10))
        sl = a.assemble(roles={"analyst"})
        assert sl.tokens_used <= 100
        assert len(sl.filtered) > 0


class TestContextContract:
    def test_sufficiency_stop(self):
        a = ContextAssembler()
        a.register(ContextProvider("metric", lambda: item("metric_registry", "口径定义"), priority=80))
        contract = ContextContract("planning", required=("metric_registry",))
        sl_ok = a.assemble(step_contract=contract)
        assert contract.sufficiency_ok(sl_ok)
        a2 = ContextAssembler()  # 无 metric
        contract2 = ContextContract("planning", required=("metric_registry",))
        sl_bad = a2.assemble(step_contract=contract2)
        assert not contract2.sufficiency_ok(sl_bad)
        assert any("__missing_required__" in k for k, _ in sl_bad.filtered)

    def test_blocked_contract(self):
        a = ContextAssembler()
        a.register(ContextProvider("cols", lambda: item("raw_pii", "客户手机号"), priority=1))
        contract = ContextContract("planning", blocked=("raw_pii",))
        sl = a.assemble(step_contract=contract)
        # blocked 内容若出现即违反（默认不排除，仅检测）
        assert sl.items  # 存在
        assert len([i.key for i in sl.items if i.key == "raw_pii"]) >= 1


def test_render_prompt():
    a = ContextAssembler()
    a.register(ContextProvider("m", lambda: item("metric_registry", "GMV=已支付金额", provenance=Provenance.BUSINESS_KNOWLEDGE), priority=80))
    a.register(ContextProvider("t", lambda: item("tenant_identity", "华东区", provenance=Provenance.TENANT_ATTR), priority=90))
    contract = ContextContract("planning", required=("metric_registry",))
    sl = a.assemble(step_contract=contract)
    txt = render_prompt_template(sl, header="【系统】")
    assert "GMV=已支付金额" in txt
    assert "华东区" in txt