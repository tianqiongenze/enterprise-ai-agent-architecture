# -*- coding: utf-8 -*-
"""Autonomous Analysis Harness (第五篇第2课)。

从 while 循环到"可验证的经营分析闭环"：
Plan -> Replan -> Execute(Tool) -> Observe -> Verify -> Stop Condition
所有决策受 Autonomy Budget 限制（最大步数、最大 token、最大工具调用）。
每次工具调用写入 Run/Step/Event 事件流（统一执行模型），可持久化、可回放。
"""
from __future__ import annotations

from typing import Any, Callable, Optional, Protocol

from ...contracts.model import LlmClient, LogicalCall, Message, ModelCapability, Role
from ...contracts.runtime import EventType, Run, RunStatus, Step, StepStatus
from ...contracts.tool import CapabilityRegistry, Tool
from ...infra.gateway.llm_runtime import ReliableExecutor
from ...infra.gateway.tools import build_dataagent_toolchain, TenantDataLake


class AutonomyBudget:
    """限制 Agent 自主性：最大步数 / 最大工具调用 / 最大 token —— 解决无限循环。

    意图定义：即使模型推理失误，预算也会硬性终止 Loop。
    """

    def __init__(self, max_steps: int = 8, max_tokens: int = 20000, max_tool_calls: int = 12):
        self.max_steps = max_steps
        self.max_tokens = max_tokens
        self.max_tool_calls = max_tool_calls
        self.steps = 0
        self.tokens = 0
        self.tool_calls = 0

    def can_continue(self) -> bool:
        return self.steps < self.max_steps and self.tokens < self.max_tokens and self.tool_calls < self.max_tool_calls

    def spend_tokens(self, n: int) -> None:
        self.tokens += n


class Verifier:
    """Verifier：验证中间结果是否可信 —— 防止越跑越偏。可注入规则校验。"""

    def __init__(self, checks: Optional[list[Callable[[dict], str]]] = None):
        self.checks = checks or []

    def run(self, context: dict) -> tuple[bool, str]:
        for check in self.checks:
            msg = check(context)
            if msg:
                return False, msg
        return True, ""


class StopCondition:
    """Stop Condition：什么时候停止 —— 让 Agent 知道何时结束。"""

    def __init__(self, max_conclusions: int = 1):
        self.max_conclusions = max_conclusions
        self.conclusions = 0

    def should_stop(self, step: str, verifier_ok: bool) -> bool:
        if step == "conclusion":
            self.conclusions += 1
        if self.conclusions >= self.max_conclusions and verifier_ok:
            return True
        return False


class Harness:
    """Autonomous Analysis Harness：开放分析闭环 + 统一执行模型。"""

    def __init__(
        self,
        executor: ReliableExecutor,
        registry: CapabilityRegistry,
        model: str = "default",
        *,
        budget: Optional[AutonomyBudget] = None,
        verifier: Optional[Verifier] = None,
        stop: Optional[StopCondition] = None,
        plan_prompt_fn: Optional[Callable[[str, str], list[Message]]] = None,
    ):
        self.executor = executor
        self.registry = registry
        self.model = model
        self.budget = budget or AutonomyBudget()
        self.verifier = verifier or Verifier()
        self.stop = stop or StopCondition()

    def run(self, run: Run, tenant_id: str) -> Run:
        """执行一次完整的自主分析闭环，返回同一条 Run（含完整 Step/Event 轨迹）。"""
        cap = self.executor._registry.resolve(self.model)
        run.status = RunStatus.RUNNING
        run.add_event(EventType.RUN_STARTED, data={"tenant": tenant_id})

        step_names = [
            ("plan", "确认指标口径与制定分析计划"),
            ("query", "查询经营数据"),
            ("analyze", "Python 分析 / 证据验证"),
            ("conclusion", "生成结论与建议"),
        ]
        step_objs = [run.add_step(n) for n, _ in step_names]

        last_msg = ""          # 最近的模型结论
        last_result: dict = {}

        # Step 1: Plan
        s = step_objs[0]
        s.status = StepStatus.RUNNING
        s.started_at = __import__("time").time()
        run.add_event(EventType.STEP_STARTED, step_id=s.step_id, data={"name": s.name})
        plan_msg = self._plan(run, tenant_id)
        s.output = {"plan": plan_msg}
        s.status = StepStatus.SUCCEEDED
        s.finished_at = __import__("time").time()

        # Step 2..3: 迭代 —— 依据工具调用结果（query, analyze 固定串联）
        for current_step in (1, 2):
            if not self.budget.can_continue():
                break
            self.budget.steps += 1
            s = step_objs[current_step]
            s.status = StepStatus.RUNNING
            s.started_at = __import__("time").time()
            run.add_event(EventType.STEP_STARTED, step_id=s.step_id, data={"name": s.name})
            for tool_schema in self.registry.visible_for(tenant_id=tenant_id, roles={"analyst"}):
                tool = self.registry.get(tool_schema["function"]["name"])
                if tool is None:
                    continue
                if tool.risk_level.name != "READONLY":
                    continue
                # 决定对此工具进行调用 —— 以分析步为例调用 query_metric / python_analyze
                if s.name == "query" and tool.name == "query_metric":
                    res = tool.invoke({"tenant_id": tenant_id})
                    run.add_event(EventType.TOOL_CALL, step_id=s.step_id, data={"tool": tool.name})
                    self.budget.tool_calls += 1
                    last_result = res.value
                    s.input["query_metric_result"] = res.value
                elif s.name == "analyze" and tool.name == "python_analyze":
                    if last_result:
                        res = tool.invoke({"metric": "gmv", "vs": 0, "data": last_result})
                        run.add_event(EventType.TOOL_RESULT, step_id=s.step_id, data={"result": res.value})
                        s.input["analysis"] = res.value
                        self.budget.tool_calls += 1
            s.status = StepStatus.SUCCEEDED
            s.finished_at = __import__("time").time()

        # Step 4: Conclusion —— 生成结论与建议
        s = step_objs[3]
        s.status = StepStatus.RUNNING
        s.started_at = __import__("time").time()
        run.add_event(EventType.STEP_STARTED, step_id=s.step_id, data={"name": s.name})
        last_msg = self._conclude(run, tenant_id, last_result)
        s.output = {"conclusion": last_msg}
        s.status = StepStatus.SUCCEEDED
        s.finished_at = __import__("time").time()

        # Verifier + Stop
        ctx = {"conclusion": last_msg, "last_result": last_result}
        verifier_ok, verr = self.verifier.run(ctx)
        if not verifier_ok:
            run.add_event(EventType.STEP_FAILED, data={"reason": verr})
        run.add_event(EventType.RUN_SUCCEEDED, data={"verifier_ok": verifier_ok})

        run.status = RunStatus.SUCCEEDED
        run.checkpoint = run.to_checkpoint()
        return run

    # ---------------- private ----------------
    def _plan(self, run: Run, tenant_id: str) -> str:
        call = LogicalCall.new(
            task="planning",
            capability=self.executor._registry.resolve(self.model),
            messages=[
                Message(role=Role.SYSTEM, content="你是零售经营分析 Agent。请输出分析计划。"),
                Message(role=Role.USER, content=f"租户={tenant_id} 任务={run.query} 请规划：确认指标口径、查询、诊断、建议。"),
            ],
        )
        res = self.executor.complete(call)
        usage = res.usage
        if usage:
            self.budget.spend_tokens(usage.total_tokens)
        run.budget_used_input += usage.prompt_tokens if usage else 0
        run.budget_used_output += usage.completion_tokens if usage else 0
        return res.text

    def _conclude(self, run: Run, tenant_id: str, last_result: dict) -> str:
        call = LogicalCall.new(
            task="conclusion",
            capability=self.executor._registry.resolve(self.model),
            messages=[
                Message(role=Role.SYSTEM, content="综合查询与分析结果，给出经营诊断结论与建议。"),
                Message(role=Role.USER, content=f"指标结果={last_result}"),
            ],
        )
        res = self.executor.complete(call)
        if res.usage:
            run.budget_used_input += res.usage.prompt_tokens
            run.budget_used_output += res.usage.completion_tokens
        return res.text