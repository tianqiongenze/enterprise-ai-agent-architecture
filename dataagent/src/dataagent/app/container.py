# -*- coding: utf-8 -*-
"""应用层装配 (Application / Composition Root)。

把契约层、领域层、基础设施、适配器组装成可运行的 DataAgent 管线。
遵循 DDD：应用层只编排用例，不承载业务规则。

本文件是一个"依赖注入根"，提供统一的 Runtime 容器 (DataAgentContainer)，
供 CLI、Web、测试三端复用 —— 保证离线可运行、可测试、可部署。
"""
from __future__ import annotations

from typing import Any, Optional

from ..adapters.llm.fake_client import FakeLlmClient
from ..contracts.model import ModelCapability
from ..infra.context.assembler import (
    ContextAssembler,
    ContextContract,
    ContextItem,
    ContextProvider,
    Provenance,
)
from ..infra.gateway.llm_runtime import ModelRegistry, ReliableExecutor, Router
from ..infra.gateway.tools import TenantDataLake, build_dataagent_toolchain
from ..infra.memory.memory import (
    InMemoryMemoryStore,
    MemoryOps,
    MemoryPolicyEngine,
    MemoryRecall,
    MemoryWritePipeline,
    default_memory_validate,
)
from ..infra.metrics.eval_ops import BatchEvalRunner, RegressionGate
from ..infra.runtime.harness import AutonomyBudget, Harness, StopCondition, Verifier
from ..infra.runtime.workflow import (
    DurableWorkflowExecutor,
    HumanApprovalGate,
    IdempotencyStore,
    InMemoryApprovalPort,
    InMemoryRunStore,
)
from ..infra.sandbox.executor import NetworkPolicy, PythonSandbox
from ..infra.security.guards import CredentialBroker, InjectionGuard, QueryGateway, SQLPolicy, TenancyContext
from ..infra.skills.skill import SkillRegistry, build_anomaly_skill


class DataAgentContainer:
    """DataAgent 的运行时组合根。"""

    def __init__(self, seed_orders: Optional[dict[str, list[dict]]] = None) -> None:
        # ---- LLM Runtime (第四篇) ----
        self.registry = ModelRegistry()
        self.registry.register(ModelCapability(model="luna", provider="mock"))
        self.registry.register(ModelCapability(model="default", provider="mock"))
        self.registry.alias("analyze", "luna")
        self.registry.alias("planning", "luna")
        self.registry.alias("conclusion", "default")
        self.router = Router(self.registry)
        self.router.add_route("analyze", ["luna", "default"])
        self.router.add_route("planning", ["luna", "default"])
        self.router.add_route("conclusion", ["default", "luna"])
        self.client = FakeLlmClient()
        self.executor = ReliableExecutor(self.client, self.router, self.registry, max_attempts=2)

        # ---- 数据湖 & 工具 (第七篇) ----
        self.lake = TenantDataLake()
        if seed_orders:
            for tenant, rows in seed_orders.items():
                self.lake.set_orders(tenant, rows)
        self.tools = build_dataagent_toolchain(self.lake)

        # ---- 上下文 (第六篇) ----
        self.ctx = ContextAssembler(token_budget=6000)
        self.ctx.register(ContextProvider(
            "tenant_identity",
            lambda: ContextItem(
                key="tenant_identity",
                content="租户身份：零售商家，华东区运营",
                provenance=Provenance.TENANT_ATTR,
            ),
            priority=90,
        ))
        self.metric_ctx = ContextProvider(
            "metric_registry",
            lambda: ContextItem(
                key="metric_registry",
                content="核心指标：GMV=已支付订单金额合计；订单数；客单价=GMV/单量；转化率；退款率",
                provenance=Provenance.BUSINESS_KNOWLEDGE,
            ),
            priority=80,
        )
        self.ctx.register(self.metric_ctx)

        # ---- Memory (第八篇) ----
        self.mem_store = InMemoryMemoryStore()
        self.mem_policy = MemoryPolicyEngine(validate=default_memory_validate)
        self.mem_write = MemoryWritePipeline(self.mem_store, self.mem_policy)
        self.mem_recall = MemoryRecall(self.mem_store)
        self.mem_ops = MemoryOps(self.mem_store)

        # ---- Skill (第七篇第4课) ----
        self.skills = SkillRegistry()
        build_anomaly_skill(self.skills)

        # ---- Runtime / Workflow (第五篇) ----
        self.run_store = InMemoryRunStore()
        self.approval_port = InMemoryApprovalPort(auto_approve=True)
        self.approval = HumanApprovalGate(self.approval_port)
        self.idem = IdempotencyStore()
        self.harness = Harness(
            self.executor,
            self.tools,
            model="luna",
            budget=AutonomyBudget(max_steps=6),
            verifier=Verifier(),
            stop=StopCondition(),
        )
        self.workflow = DurableWorkflowExecutor(
            store=self.run_store,
            approval=self.approval,
            idem=self.idem,
            harness_runner=lambda run, ctx: self.harness.run(run, "ten_a"),
        )

        # ---- Security (第二/七篇) ----
        self.creds = CredentialBroker()
        self.injection = InjectionGuard()
        self.sql_policy = SQLPolicy()
        self.query_gateway = QueryGateway(self.sql_policy)
        self.sandbox = PythonSandbox()
        self.net_policy = NetworkPolicy(allow=("odbc.db",))

    # ---- 用例：一次完整经营诊断 ----
    def analyze(self, query: str, tenant_id: str = "ten_a") -> Any:
        """运行一次经营分析：通过 Durable Workflow 包裹 Autonomous Harness。

        返回完整 Run（含 Run Timeline / Checkpoint），可序列化、可回放。
        """
        from ..contracts.runtime import Run

        run = Run(query=query, tenant_id=tenant_id, task_type="analysis")
        self.run_store.save(run)
        return self.workflow_analysis(run)

    def workflow_analysis(self, run: Any) -> Any:
        from ..contracts.runtime import Run
        from ..infra.runtime.workflow import WorkflowDefinition, WorkflowNode

        wf = WorkflowDefinition("analysis", nodes=[
            WorkflowNode("autonomous_analysis", "harness"),
            WorkflowNode("verifier", "verifier", fn=lambda r, i: {"verified": True}),
            # 高风险副作用：预算调整预审 —— Human Approval Gate
            WorkflowNode("budget_adjust", "human_gate", approval_action="adjust_budget", risk_level="high"),
        ])
        return self.workflow.execute(wf, run)


def default_seed() -> dict[str, list[dict]]:
    """默认演示数据集：华东/华南两区域订单，体现"多租户 + 区域"语义。"""
    return {
        "ten_a": [
            {"order_id": f"a{i}", "region": "华东", "amount": 300, "conversion_rate": 0.5}
            for i in range(8)
        ]
        + [
            {"order_id": f"a{i}", "region": "华南", "amount": 120, "conversion_rate": 0.3}
            for i in range(8, 12)
        ],
        "ten_b": [
            {"order_id": f"b{i}", "region": "华北", "amount": 260, "conversion_rate": 0.6}
            for i in range(6)
        ],
    }