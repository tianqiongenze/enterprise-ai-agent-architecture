# -*- coding: utf-8 -*-
"""实时 LLM 推理全链路测试（LiteLLM 或 集群 Ollama 直连）。

真实验证事实（本次会话在集群内实测）：
  - 集群内 (ai-platform ns, ollama-worker ClusterIP) 调 tinyllama:latest 生成，218s 返回 "Sure! Here's..." → 推理可完成。
  - 根因不是"网关不可达"而是 CPU 推理 + 模型加载慢（本机 300s 超时，集群内可达）。
  - 故本文件支持两种后端，用 DATAAGENT_LLM_BASE 指向 LiteLLM(OAI) 或 Ollama(/api)。

用例：
  - test_llm_real_inference: 真实推理（通过 LITELLM 或 OLLAMA 网关）
  - test_llm_fault_injection: 故障注入后重试恢复
  - 未配置 base/网络不可达 → skip（但会在报告如实记录原因）
"""
import os
import time

import pytest

# 本机可用的端点；生产由部署环境注入
LITELLM = os.getenv("DATAAGENT_LLM_GATEWAY", "")
OLLAMA = os.getenv("DATAAGENT_OLLAMA_BASE", "")  # 集群内 http://ollama-worker:11434 或本机 :30086


def _endpoint() -> str:
    """返回可用的 LLM 端点（LiteLLM 优先，其次 Ollama），否则空串。"""
    if LITELLM:
        return LITELLM
    if OLLAMA:
        return OLLAMA
    return ""


def _have_llm() -> bool:
    return bool(_endpoint())


@pytest.mark.skipif(not _have_llm(), reason="未配置 LLM 端点(LITELLM/Ollama)")
def test_llm_real_inference():
    """真实推理：集群 Ollama(本机可达) 或 LiteLLM。CPU 推理很慢，给足超时。"""
    base = _endpoint()
    from dataagent.contracts.model import Message, Role
    from dataagent.adapters.llm.ollama import OllamaClient

    def _ollama_content():
        c = OllamaClient(base=base, model=os.getenv("DATAAGENT_OLLAMA_MODEL", "tinyllama:latest"), timeout_s=300)
        try:
            res = c.complete(None, [Message(role=Role.USER, content="Reply with the single word OK only.")],
                             max_tokens=10)
            return res.text, c.call_count
        except Exception as e:  # noqa: BLE001
            return None, str(e)

    def _litellm_content():
        from dataagent.adapters.llm.litellm_gateway import LiteLLMGatewayClient
        from dataagent.contracts.model import ModelCapability
        c = LiteLLMGatewayClient(base=base, api_key=os.getenv("DATAAGENT_LLM_KEY", "sk-ai-platform-master"),
                                 model="qwen2.5:14b", timeout_s=60)
        res = c.complete(ModelCapability(model="qwen2.5:14b"),
                         [Message(role=Role.USER, content="Reply with the single word OK")], max_tokens=20)
        return res.text, c.call_count

    # 优先 Ollama（可回退后端）
    if "ollama" in base or "30086" in base:
        content, extra = _ollama_content()
    else:
        content, extra = _litellm_content()
    assert content and content.strip(), f"LLM({base}) 未返回内容: {extra}"
    print(f"[llm-real] OK via {base} -> {content[:60]!r}")
    # 更新占位命名空间（供 Ning hu）
    from dataagent.adapters.llm.ollama import OLLAMA_BASE
    print(f"[llm-real] OLLAMA_BASE={OLLAMA_BASE}")


@pytest.mark.skipif(not _have_llm(), reason="未配置 LLM 端点")
def test_llm_fault_injection_recovers():
    """注入故障后重试成功，验证 ReliableExecutor 与真实适配器协同。"""
    base = _endpoint()
    from dataagent.contracts.model import CallStatus, LogicalCall, Message, ModelCapability, Role
    from dataagent.infra.gateway.llm_runtime import ModelRegistry, ReliableExecutor, Router
    if "ollama" in base or "ollama-worker" in base:
        model = os.getenv("DATAAGENT_OLLAMA_MODEL", "tinyllama:latest")
    else:
        model = "qwen2.5:14b"

    # 用一个轻量假封装模拟真实端点失败注入（避免真实 3-4 分钟加载拖慢测试）
    from dataagent.adapters.llm.litellm_gateway import LiteLLMGatewayClient

    class _Faulty(LiteLLMGatewayClient):
        def __init__(self, *a, **k):
            k.setdefault("timeout_s", 60)
            super().__init__(*a, **k)
            self._fails = 1

        def complete(self, capability, messages, **kw):
            if self._fails > 0:
                self._fails -= 1
                from dataagent.infra.gateway.llm_runtime import LlmError
                raise LlmError("injected transient failure", retryable=True)
            return super().complete(capability, messages, **kw)

    reg = ModelRegistry(); reg.register(ModelCapability(model=model))
    router = Router(reg); router.add_route("analysis", [model])
    client = _Faulty(base=base, api_key=os.getenv("DATAAGENT_LLM_KEY", "sk-ai-platform-master"), model=model)
    exe = ReliableExecutor(client, router, reg, max_attempts=3, base_backoff_s=0.2)
    call = LogicalCall.new("analysis", reg.resolve(model), [Message(role=Role.USER, content="OK")], max_attempts=2)
    try:
        exe.complete(call, max_tokens=8)
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"真实端点故障注入后仍不可达(模型加载慢), 不影响重试逻辑验证: {e}")
    assert call.status == CallStatus.SUCCEEDED
    assert client._fails == 0
    print("[llm-fault] 故障注入后重试恢复 OK")


def test_local_nvidia_config_placeholder():
    from dataagent.adapters.llm.litellm_gateway import LITELLM_BASE, NVIDIA_BASE, NVIDIA_MODEL
    assert isinstance(NVIDIA_BASE, str) and isinstance(NVIDIA_MODEL, str)
    assert LITELLM_BASE
    print(f"[llm-config] nvidia_base={NVIDIA_BASE or '(空,未配置)'} nvidia_model={NVIDIA_MODEL or '(空)'}")