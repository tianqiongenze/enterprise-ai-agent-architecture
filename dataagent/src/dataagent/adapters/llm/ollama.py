# -*- coding: utf-8 -*-
"""适配器：Ollama 原生后端（真实本地/集群模型推理）。

解决场景：当 LiteLLM 网关不可达时，用集群/本地 Ollama（qwen3:4b、tinyllama、deepseek-r1:7b 等）
作为真实推理回退。

端点（实测）：
  - 集群内：http://ollama-worker:11434  （ai-platform 命名空间）
  - 本机可达：http://10.167.2.175:30086   (ollama-worker-nodeport /api/tags 可达)
实测：tinyllama:latest 集群内生成 218s（CPU 推理，慢但成功）；qwen3 等较大模型需更长加载。

Ollama 原生 `/api/chat` 返回 message.content；本适配器把它包装为 CompletionResult。
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

OLLAMA_BASE = os.getenv("DATAAGENT_OLLAMA_BASE", "http://10.167.2.175:30086")
OLLAMA_MODEL = os.getenv("DATAAGENT_OLLAMA_MODEL", "tinyllama:latest")


class OllamaClient(LlmClient):
    """原生 Ollama 客户端：真实推理（CPU 慢）、支持故障注入。"""

    def __init__(self, base: str = OLLAMA_BASE, model: str = OLLAMA_MODEL,
                 *, fail_times: int = 0, timeout_s: float = 360.0, latency_s: float = 0.0):
        self.base = base.rstrip("/")
        self.model = model
        self.fail_times = fail_times
        self.timeout_s = timeout_s
        self.latency_s = latency_s
        self.call_count = 0
        import urllib.request
        self._ur = urllib.request

    def complete(self, capability, messages, *, temperature=0.0, max_tokens=None,
                 structured=None, tools=None) -> CompletionResult:
        from ...infra.gateway.llm_runtime import LlmError

        self.call_count += 1
        if self.latency_s:
            time.sleep(self.latency_s)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise LlmError("simulated ollama failure", retryable=True)

        model = (capability.model if capability and capability.model else self.model)
        oai_messages = [
            {"role": ("assistant" if m.role == Role.ASSISTANT else m.role.value),
             "content": m.content} for m in messages
        ]
        payload = {"model": model, "messages": oai_messages, "stream": False,
                   "options": {"num_predict": max_tokens or 64, "temperature": temperature}}
        req = self._ur.Request(f"{self.base}/api/chat", data=json.dumps(payload).encode(),
                               headers={"Content-Type": "application/json"})
        try:
            with self._ur.urlopen(req, timeout=self.timeout_s) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            raise LlmError(f"ollama chat error: {e}", retryable=True) from e

        text = (data.get("message") or {}).get("content", "")
        usage = Usage(
            prompt_tokens=int((data.get("prompt_eval_count") or 0)),
            completion_tokens=int((data.get("eval_count") or 0)),
        )
        # Ollama 不支持原生 tools 参数格式；此处返回空（工具调用由上层决定）
        return CompletionResult(text=text, tool_calls=[], usage=usage, model=model)

    def stream(self, capability, messages, **kw):
        res = self.complete(capability, messages, **kw)
        for ch in res.text:
            yield ch


def make_ollama_client() -> OllamaClient:
    return OllamaClient(
        base=os.getenv("DATAAGENT_OLLAMA_BASE", OLLAMA_BASE),
        model=os.getenv("DATAAGENT_OLLAMA_MODEL", OLLAMA_MODEL),
    )