# -*- coding: utf-8 -*-
"""适配器：Fake/Stub LLM Client（离线可运行、可测试、可注入故障）。

用于课程演示与测试 —— 不依赖任何外部 API，所有用例可离线运行。
通过 fault injection 支持第四篇第3课的"真实故障注入"实战。
"""
from __future__ import annotations

import time
from typing import Any, Optional, Sequence

from ...contracts.model import (
    CompletionResult,
    LlmClient,
    Message,
    ModelCapability,
    Role,
    ToolCall,
    Usage,
)


class FakeLlmClient(LlmClient):
    """一个可编程的假模型客户端。

    通过 handler 自定义"如何从消息序列生成结果"，从而模拟：
    - 正常回答（分析规划、结论等）
    - 结构化输出
    - 工具调用决策
    - 故障（抛异常、超时、返回非法结构化输出）
    """

    def __init__(
        self,
        handler: Optional[Any] = None,
        *,
        fail_times: int = 0,
        fail_error: str = "Simulated upstream failure",
        latency_s: float = 0.0,
        structured_handler: Optional[Any] = None,
        fail_mode: str = "error",
        retry_after_s: float = 0.5,
    ):
        self.handler = handler
        self.structured_handler = structured_handler
        self.fail_times = fail_times
        self.fail_error = fail_error
        self.latency_s = latency_s
        # 故障类型（GAP-13 借鉴：四象限补齐——限流型/超时型）
        # error: 瞬时 5xx | rate_limit: 429+Retry-After（服务端指示退避）| timeout: 上游挂起后超时
        self.fail_mode = fail_mode
        self.retry_after_s = retry_after_s
        self.call_count = 0

    def complete(
        self,
        capability: ModelCapability,
        messages: Sequence[Message],
        *,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        structured: Optional[type] = None,
        tools: Optional[Sequence[dict[str, Any]]] = None,
    ) -> CompletionResult:
        from ...infra.gateway.llm_runtime import LlmError

        self.call_count += 1
        if self.latency_s:
            time.sleep(self.latency_s)
        if self.fail_times > 0:
            self.fail_times -= 1
            if self.fail_mode == "rate_limit":
                raise LlmError(
                    "429 rate limited (server-directed backoff)",
                    retryable=True, retry_after_s=self.retry_after_s,
                )
            if self.fail_mode == "timeout":
                raise LlmError("upstream timeout after hang", retryable=True)
            raise LlmError(self.fail_error, retryable=True)

        usage = Usage(
            prompt_tokens=len("".join(m.content for m in messages)) // 3 + 10,
            completion_tokens=64,
        )
        tool_calls: list[ToolCall] = []

        # 工具调用决策：若 user 消息包含 "调用工具:<name>|<json>"
        for m in messages:
            if m.role == Role.USER and m.content.startswith("调用工具:"):
                spec = m.content[len("调用工具:"):]
                name, _, argstr = spec.partition("|")
                import json
                try:
                    args = json.loads(argstr or "{}")
                except Exception:  # noqa: BLE001
                    args = {}
                tool_calls.append(
                    ToolCall(id=f"tc_{self.call_count}", name=name, arguments=args)
                )

        if structured is not None:
            if self.structured_handler is not None:
                data = self.structured_handler(messages, self.call_count)
            else:
                data = self._default_structured(structured, messages)
            return CompletionResult(
                text="", structured=data, usage=usage, model=capability.model
            )

        if self.handler is not None:
            text = self.handler(messages, self.call_count)
        else:
            text = self._default_text(messages)
        return CompletionResult(
            text=text, tool_calls=tool_calls, usage=usage, model=capability.model
        )

    def stream(self, capability, messages, **kw):
        text = (self.handler(messages, 0)) if self.handler else "streamed"
        for ch in text:
            yield ch

    # ---------------- 默认行为 ----------------
    def _default_structured(self, structured: type, messages: Sequence[Message]) -> dict[str, Any]:
        """从消息中按字段名提取可填写的结构化字段；无法识别则返回空结构。"""
        import json

        last = messages[-1].content if messages else ""
        data: dict[str, Any] = {}
        for m in messages:
            if m.role == Role.USER and m.content.startswith("结构化:"):
                spec = m.content[len("结构化:"):]
                try:
                    return json.loads(spec)
                except Exception:  # noqa: BLE001
                    return {}
        # 尝试用默认 schema 返回含所有 required 字段的空值
        try:
            schema = structured.model_json_schema() if hasattr(structured, "model_json_schema") else {}
        except Exception:  # noqa: BLE001
            schema = {}
        required = schema.get("required", [])
        for r in required:
            data[r] = ""
        if required:
            if "steps" in required:
                data["steps"] = ["查询数据", "诊断原因"]
            if "conclusion" in required:
                data["conclusion"] = last[:40] or "结论"
            if "evidence" in required:
                data["evidence"] = []
        return data

    def _default_text(self, messages: Sequence[Message]) -> str:
        last = messages[-1].content if messages else ""
        if "规划" in last or "plan" in last.lower():
            return "1. 确认指标口径\n2. 查询数据\n3. 诊断原因\n4. 生成建议"
        if "确认指标" in last:
            return "GMV 口径：已支付订单金额合计，含已退货部分待评估。"
        return "基于查询结果，GMV 下滑主要来自华东区转化率下降，建议补充库存。"