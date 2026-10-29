# -*- coding: utf-8 -*-
"""Autonomous Analysis Harness (第五篇第2课)。

从 while 循环到"可验证的经营分析闭环"：
Plan -> Replan -> Execute(Tool) -> Observe -> Verify -> Stop Condition
所有决策受 Autonomy Budget 限制（最大步数、最大 token、最大工具调用）。
每次工具调用写入 Run/Step/Event 事件流（统一执行模型），可持久化、可回放。

工程纪律（对齐参照工程 dataagent-course 的不变式设计）：
- **时钟可注入**：时间只经 ``clock`` 流入，测试用受控时钟即可确定性断言耗时语义；
- **预算只能经方法消费**：``spend_step()`` / ``spend_tool_call()`` 是唯一入口，
  避免"直接改字段绕过上限检查"这类静默失控；
- **Verifier 失败 ≠ 成功**：验证不通过的运行必须落 ``FAILED``（完成判据只挂
  可观测事实上），而不是"带病 SUCCEEDED"。
"""
from __future__ import annotations

import time
from typing import Any, Callable, Optional

from ...contracts.model import LogicalCall, Message, Role
from ...contracts.runtime import EventType, Run, RunStatus, StepStatus
from ...contracts.tool import CapabilityRegistry
from ...infra.gateway.llm_runtime import ReliableExecutor

Clock = Callable[[], float]


class VerifierFailedError(Exception):
    """Verifier 验证失败 —— 完成判据未满足，运行不得标记成功。

    作为节点级异常抛出，由 DurableWorkflowExecutor 捕获并把 Run 落 FAILED：
    完成判据只挂可观测事实上（对齐参照工程的 ORCHESTRATION 纪律）。
    """

    def __init__(self, reason: str):
        super().__init__(f"verifier failed: {reason}")
        self.reason = reason


class AutonomyBudget:
    """限制 Agent 自主性：最大步数 / 最大工具调用 / 最大 token —— 解决无限循环。

    意图定义：即使模型推理失误，预算也会硬性终止 Loop。
    消费只能经 ``spend_*`` 方法，直接改公开计数字段会在 Code Review 中被拦截。
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

    def spend_step(self) -> None:
        """消费 1 步预算（唯一合法入口）。"""
        self.steps += 1

    def spend_tool_call(self) -> None:
        """消费 1 次工具调用预算（唯一合法入口）。"""
        self.tool_calls += 1

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
        clock: Optional[Clock] = None,
    ):
        self.executor = executor
        self.registry = registry
        self.model = model
        self.budget = budget or AutonomyBudget()
        self.verifier = verifier or Verifier()
        self.stop = stop or StopCondition()
        self._clock: Clock = clock or time.time

    def run(self, run: Run, tenant_id: str) -> Run:
        """执行一次完整的自主分析闭环，返回同一条 Run（含完整 Step/Event 轨迹）。

        终态归属纪律：**Run 的终态由 DurableWorkflowExecutor 所有**——本方法只写
        Step/Event 与消费预算，不写 ``run.status``（RUNNING 初始化除外）；
        Verifier 失败时抛 :class:`VerifierFailedError`，由工作流把 Run 落 FAILED。
        这样 harness 作为 workflow 子节点不会与外层执行器争夺终态。
        """
        cap = self.executor.registry.resolve(self.model)
        if run.status == RunStatus.PENDING:
            run.status = RunStatus.RUNNING
        run.add_event(EventType.RUN_STARTED, data={"tenant": tenant_id})
        # 预算语义修正（评测矩阵 GAP-26）：self.budget 是**限额模板**（limit 常驻），
        # 计数器必须 per-run 全新——否则同一容器第二次分析起预算被上一轮耗尽，
        # query/analyze 步骤静默跳过（评测矩阵抓到的真实跨 Run 泄漏）。
        budget = AutonomyBudget(max_steps=self.budget.max_steps,
                                max_tokens=self.budget.max_tokens,
                                max_tool_calls=self.budget.max_tool_calls)

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
        s.started_at = self._clock()
        run.add_event(EventType.STEP_STARTED, step_id=s.step_id, data={"name": s.name})
        plan_msg = self._plan(run, tenant_id, budget)
        s.output = {"plan": plan_msg}
        s.status = StepStatus.SUCCEEDED
        s.finished_at = self._clock()

        # Step 2..3: 迭代 —— 依据工具调用结果（query, analyze 固定串联）
        executed_query = False
        for current_step in (1, 2):
            if not budget.can_continue():
                break
            budget.spend_step()
            s = step_objs[current_step]
            s.status = StepStatus.RUNNING
            s.started_at = self._clock()
            run.add_event(EventType.STEP_STARTED, step_id=s.step_id, data={"name": s.name})
            for tool_schema in self.registry.visible_for(tenant_id=tenant_id, roles={"analyst"}):
                tool = self.registry.get(tool_schema["function"]["name"])
                if tool is None:
                    continue
                if tool.risk_level.name != "READONLY":
                    continue
                # 决定对此工具进行调用 —— 以分析步为例调用 query_metric / python_analyze
                if s.name == "query" and tool.name == "query_metric":
                    executed_query = True
                    res = tool.invoke({"tenant_id": tenant_id})
                    run.add_event(EventType.TOOL_CALL, step_id=s.step_id, data={"tool": tool.name})
                    budget.spend_tool_call()
                    last_result = res.value
                    s.input["query_metric_result"] = res.value
                elif s.name == "analyze" and tool.name == "python_analyze":
                    if last_result:
                        res = tool.invoke({"metric": "gmv", "vs": 0, "data": last_result})
                        run.add_event(EventType.TOOL_RESULT, step_id=s.step_id, data={"result": res.value})
                        s.input["analysis"] = res.value
                        budget.spend_tool_call()
            s.status = StepStatus.SUCCEEDED
            s.finished_at = self._clock()

        # Step 4: Conclusion —— 生成结论与建议
        # 终态语义修正（评测集 v2 反例抓到，GAP-30）：预算耗尽导致关键分析步未执行时，
        # 不得"跳过数据直接出结论"地带病成功——fail-closed 抛节点级失败（Run FAILED）
        if not executed_query and not budget.can_continue():
            s = step_objs[3]
            s.status = StepStatus.FAILED
            s.error = "预算耗尽：关键分析步骤（query/analyze）未执行"
            run.add_event(EventType.STEP_FAILED, step_id=s.step_id,
                          data={"reason": s.error, "budget": {"steps": budget.steps,
                                                              "tokens": budget.tokens,
                                                              "tool_calls": budget.tool_calls}})
            raise VerifierFailedError("预算耗尽：关键分析步骤未执行")
        s = step_objs[3]
        s.status = StepStatus.RUNNING
        s.started_at = self._clock()
        run.add_event(EventType.STEP_STARTED, step_id=s.step_id, data={"name": s.name})
        last_msg = self._conclude(run, tenant_id, last_result, budget)
        s.output = {"conclusion": last_msg}
        s.status = StepStatus.SUCCEEDED
        s.finished_at = self._clock()

        # Verifier + Stop —— 完成判据只挂可观测事实上（节点级失败语义）
        ctx = {"conclusion": last_msg, "last_result": last_result}
        verifier_ok, verr = self.verifier.run(ctx)
        if verifier_ok:
            run.add_event(EventType.EVAL, data={"verifier_ok": True})
        else:
            s.status = StepStatus.FAILED
            s.error = f"verifier: {verr}"
            run.add_event(EventType.STEP_FAILED, step_id=s.step_id, data={"reason": verr})
            raise VerifierFailedError(verr)
        run.checkpoint = run.to_checkpoint()
        return run

    # ---------------- private ----------------
    def _plan(self, run: Run, tenant_id: str, budget: AutonomyBudget) -> str:
        call = LogicalCall.new(
            task="planning",
            capability=self.executor.registry.resolve(self.model),
            messages=[
                Message(role=Role.SYSTEM, content="你是零售经营分析 Agent。请输出分析计划。"),
                Message(role=Role.USER, content=f"租户={tenant_id} 任务={run.query} 请规划：确认指标口径、查询、诊断、建议。"),
            ],
        )
        res = self.executor.complete(call)
        usage = res.usage
        if usage:
            budget.spend_tokens(usage.total_tokens)
        run.budget_used_input += usage.prompt_tokens if usage else 0
        run.budget_used_output += usage.completion_tokens if usage else 0
        return res.text

    def _conclude(self, run: Run, tenant_id: str, last_result: dict, budget: AutonomyBudget) -> str:
        call = LogicalCall.new(
            task="conclusion",
            capability=self.executor.registry.resolve(self.model),
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
