# -*- coding: utf-8 -*-
"""第五轮特性测试：故障四象限补齐（限流/超时型）+ 队列 memory 后端 + 架构元测试。"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from dataagent.adapters.llm.fake_client import FakeLlmClient
from dataagent.contracts.model import LogicalCall, Message, ModelCapability, Role
from dataagent.infra.gateway.llm_runtime import (
    LlmError,
    ModelRegistry,
    ReliableExecutor,
    Router,
)

ROOT = Path(__file__).resolve().parents[3]


class _Clock:
    def __init__(self, start=0.0):
        self.now = start

    def monotonic(self):
        return self.now

    def sleep(self, s):
        self.now += s


def _executor(client, clock, max_attempts=3, base_backoff=0.2):
    reg = ModelRegistry()
    reg.register(ModelCapability(model="demo"))
    rt = Router(reg)
    rt.add_route("t", ["demo"])
    return ReliableExecutor(client, rt, reg, max_attempts=max_attempts,
                            base_backoff_s=base_backoff, sleep=clock.sleep,
                            monotonic=clock.monotonic)


def _call():
    reg = ModelRegistry()
    reg.register(ModelCapability(model="demo"))
    return LogicalCall.new(task="t", capability=reg.resolve("demo"),
                           messages=[Message(role=Role.USER, content="x")])


class TestFaultQuadrantComplete:
    """docs/13 借鉴动作：故障四象限补齐——限流型（429+Retry-After）与超时型。"""

    def test_rate_limit_uses_server_directed_backoff(self):
        """429 Retry-After：退避采用**服务端指示**而非本地指数退避。"""
        clock = _Clock()
        client = FakeLlmClient(fail_times=2, fail_mode="rate_limit", retry_after_s=0.5)
        ex = _executor(client, clock, base_backoff=0.2)
        r = ex.complete(_call())
        assert r.text
        assert clock.now == pytest.approx(1.0)   # 0.5 + 0.5（不是 0.2+0.4）
        assert ex.stats.retries == 2

    def test_timeout_fault_uses_exponential_backoff(self):
        """超时型故障：无服务端指示 → 本地指数退避（封顶语义不变）。"""
        clock = _Clock()
        client = FakeLlmClient(fail_times=2, fail_mode="timeout")
        ex = _executor(client, clock, base_backoff=0.2)
        ex.complete(_call())
        assert clock.now == pytest.approx(0.6)   # 0.2 + 0.4

    def test_rate_limit_exhaustion_carries_message(self):
        clock = _Clock()
        client = FakeLlmClient(fail_times=9, fail_mode="rate_limit", retry_after_s=0.1)
        ex = _executor(client, clock, max_attempts=2)
        with pytest.raises(LlmError) as ei:
            ex.complete(_call())
        assert "429" in str(ei.value) and "[最后尝试模型: demo]" in str(ei.value)

    def test_error_fault_regression(self):
        """error 型（原 fail_error）回归钉住：缺省行为不变。"""
        clock = _Clock()
        client = FakeLlmClient(fail_times=1)
        ex = _executor(client, clock)
        ex.complete(_call())
        assert clock.now == pytest.approx(0.2)


class TestQueueMemoryBackend:
    """memory 后端（env 门控）：探针/离线 worker 的队列通道。"""

    @classmethod
    def setup_class(cls):
        # dataagent 测试环境默认不含 services 路径（root conftest 不加载）——显式注入
        svc = str(ROOT / "services" / "src")
        if svc not in sys.path:
            sys.path.insert(0, svc)

    def setup_method(self):
        os.environ["DATAAGENT_QUEUE_BACKEND"] = "memory"

    def teardown_method(self):
        os.environ.pop("DATAAGENT_QUEUE_BACKEND", None)

    def test_enqueue_consume_fifo(self):
        from services.shared import queue as q
        q._MEMQ.clear()
        assert q.enqueue({"job": 1}) is True
        assert q.enqueue({"job": 2}) is True
        assert q.mem_queue_depth() == 2
        m1 = q.consume(timeout_ms=1)
        assert m1.task == {"job": 1}
        m2 = q.consume(timeout_ms=1)
        assert m2.task == {"job": 2}
        assert q.consume(timeout_ms=1) is None

    def test_nack_requeues_at_head(self):
        from services.shared import queue as q
        q._MEMQ.clear()
        q.enqueue({"job": 1})
        q.enqueue({"job": 2})
        m = q.consume(timeout_ms=1)
        assert m.task == {"job": 1}
        m.nack()  # 头部重投
        again = q.consume(timeout_ms=1)
        assert again.task == {"job": 1}  # 重投优先（redelivery 语义）

    def test_explicit_backend_beats_pulsar_detection(self):
        """显式 memory 后端优先于 pulsar 探测（可预测性优先）。"""
        os.environ["DATAAGENT_USE_PULSAR"] = "1"
        try:
            from services.shared import queue as q
            q._MEMQ.clear()
            q.enqueue({"job": 3})
            assert q.mem_queue_depth() == 1  # 走了 memory 而非 pulsar
        finally:
            os.environ.pop("DATAAGENT_USE_PULSAR", None)


class TestArchSelfCheck:
    """依赖方向自检元测试：自检器必须"能抓到违规"且"当前代码干净"——双断言防假阳/假阴。"""

    def test_current_codebase_clean(self):
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_arch.py")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           cwd=str(ROOT))
        assert r.returncode == 0, r.stdout + r.stderr

    def test_checker_detects_synthetic_violation(self):
        """自检器的"检出能力"必须被钉住：构造违规样例必须报警（防自检器静默失效）。"""
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            from validate_arch import FORBIDDEN, resolve_module
            import ast
            # level=3（...adapters）自 dataagent/infra/metrics/* 解析为 dataagent.adapters.*
            src = "from ...adapters.llm.fake_client import FakeLlmClient"
            node = ast.parse(src).body[0]
            f = ROOT / "dataagent/src/dataagent/infra/metrics/x.py"
            resolved = resolve_module(node, f)
            assert resolved == "dataagent.adapters.llm.fake_client"
            assert any(resolved.startswith(b) for b in FORBIDDEN["dataagent.infra."])
        finally:
            if str(ROOT / "scripts") in sys.path:
                sys.path.remove(str(ROOT / "scripts"))
