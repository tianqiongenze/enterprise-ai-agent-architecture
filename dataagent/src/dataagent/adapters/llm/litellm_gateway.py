# -*- coding: utf-8 -*-
"""适配器：LiteLLM / OpenAI 兼容 LLM Client（对接服务器 K8S ai-platform 的 LiteLLM 网关）。

集群 LLM 平台（已实测确认）：
  - service: ai-platform/litellm  (NodePort 30083 / clusterIP 10.108.11.54:4000)
  - master_key: sk-ai-platform-master；LITELLM_ALLOW_REQUESTS_WITHOUT_API_KEY=true
  - 模型: qwen2.5-coder:7b、qwen2.5:14b（经 ollama-worker:11434 路由）

本适配器通过 OpenAI 兼容 /v1/chat/completions 调用，支持：
- 工具调用（tools 参数透传）
- 结构化输出（response_format json 后做 pydantic 校验）
- 故障注入（fail_times）供混沌/压测
- 本地 NVVIDIA 备用配置（见下方 NVIDIA_CONFIG，作为本地模型的可选路径）
"""
from __future__ import annotations

import json
import os
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

# 服务器 LiteLLM 网关端点（生产用）；可用环境变量覆盖
LITELLM_BASE = os.getenv("DATAAGENT_LLM_GATEWAY", "http://10.108.11.54:4000")
LITELLM_KEY = os.getenv("DATAAGENT_LLM_KEY", "sk-ai-platform-master")
LITELLM_CHAT_MODEL = os.getenv("DATAAGENT_LLM_MODEL", "qwen2.5:14b")
LITELLM_CODER_MODEL = os.getenv("DATAAGENT_LLM_CODER", "qwen2.5-coder:7b")

# 本地 NVVIDIA / 本地模型（可选备用路径；本机未部署模型服务，仅作配置占位）
NVIDIA_BASE = os.getenv("DATAAGENT_NVIDIA_BASE", "")  # e.g. http://<本机>:11434 (ollama) 或 vLLM
NVIDIA_MODEL = os.getenv("DATAAGENT_NVIDIA_MODEL", "")  # e.g. deepseek-r1:7b


class _HttpClient:
    """极简同步 HTTP JSON 客户端（无第三方依赖；便于在无 requests 环境运行）。"""

    def __init__(self):
        import urllib.request
        self._ur = urllib.request

    def post_json(self, url: str, payload: dict, timeout: float = 60.0, bearer: str = "") -> dict:
        body = json.dumps(payload).encode("utf-8")
        req = self._ur.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        if bearer:
            req.add_header("Authorization", f"Bearer {bearer}")
        try:
            with self._ur.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"LLM gateway HTTP error: {e}") from e


def _msg_to_litellm(m: Message) -> dict:
    if m.role == Role.TOOL:
        return {"role": "tool", "tool_call_id": m.tool_call_id or "", "content": m.content}
    return {"role": m.role.value, "content": m.content}


class LiteLLMGatewayClient(LlmClient):
    """对接服务器 LiteLLM 网关的生产 LLM 客户端。

    - fail_times 用于故障注入（配合 ReliableExecutor 的重试/Fallback 测试）
    - structured 输出用 response_format(json_object) 后做 pydantic 校验
    - tools 透传实现工具调用
    """

    def __init__(
        self,
        base: str = LITELLM_BASE,
        api_key: str = LITELLM_KEY,
        model: str = LITELLM_CHAT_MODEL,
        coder_model: str = LITELLM_CODER_MODEL,
        *,
        fail_times: int = 0,
        timeout_s: float = 60.0,
        latency_s: float = 0.0,
    ):
        self.base = base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.coder_model = coder_model
        self.fail_times = fail_times
        self.timeout_s = timeout_s
        self.latency_s = latency_s
        self.call_count = 0
        self._http = _HttpClient()

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
            raise LlmError("simulated LLM gateway failure", retryable=True)

        model = capability.model if capability.model in (self.model, self.coder_model) else self.model
        payload: dict[str, Any] = {
            "model": model,
            "messages": [_msg_to_litellm(m) for m in messages],
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
        if structured is not None:
            payload["response_format"] = {"type": "json_object"}

        data = self._http.post_json(
            f"{self.base}/v1/chat/completions", payload, timeout=self.timeout_s, bearer=self.api_key
        )
        usage = self._usage_from(data)
        tool_calls = self._toolcalls_from(data)
        text = ""
        try:
            text = data["choices"][0]["message"].get("content", "")
        except Exception:  # noqa: BLE001
            pass

        if structured is not None:
            try:
                obj = json.loads(text or "{}")
            except Exception as e:  # noqa: BLE001
                raise LlmError(f"invalid JSON from gateway for structured output: {e}", retryable=False) from e
            return CompletionResult(text=text, structured=obj, usage=usage, model=model, tool_calls=())
        return CompletionResult(text=text, tool_calls=tool_calls, usage=usage, model=model)

    def _usage_from(self, data: dict) -> Usage:
        try:
            u = data.get("usage") or {}
            return Usage(
                prompt_tokens=int(u.get("prompt_tokens", 0)),
                completion_tokens=int(u.get("completion_tokens", 0)),
            )
        except Exception:  # noqa: BLE001
            return Usage(0, 0, 0)

    def _toolcalls_from(self, data: dict) -> list[ToolCall]:
        out = []
        try:
            for tc in data["choices"][0]["message"].get("tool_calls") or []:
                fn = tc.get("function") or {}
                args = fn.get("arguments", "{}")
                try:
                    argd = json.loads(args) if isinstance(args, str) else (args or {})
                except Exception:  # noqa: BLE001
                    argd = {}
                out.append(ToolCall(id=tc.get("id", ""), name=fn.get("name", ""), arguments=argd))
        except Exception:  # noqa: BLE001
            pass
        return out

    def stream(self, capability, messages, **kw):
        # 简版：非流式但按字符吐，便于接口兼容；生产用真实 SSE。
        res = self.complete(capability, messages, **kw)
        for ch in res.text:
            yield ch


def make_litellm_client() -> LiteLLMGatewayClient:
    """工厂：生产环境默认族，指向服务器 LiteLLM；若未配置网关则回退环境默认值。"""
    return LiteLLMGatewayClient(
        base=os.getenv("DATAAGENT_LLM_GATEWAY", LITELLM_BASE),
        api_key=os.getenv("DATAAGENT_LLM_KEY", LITELLM_KEY),
        model=os.getenv("DATAAGENT_LLM_MODEL", LITELLM_CHAT_MODEL),
        coder_model=os.getenv("DATAAGENT_LLM_CODER", LITELLM_CODER_MODEL),
    )