# -*- coding: utf-8 -*-
"""第六轮测试：Redis 租约后端（fake 可测）+ 通知 sink + 部署清单校验元测试。"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dataagent.contracts.runtime import (
    ApprovalDecision,
    ApprovalRequest,
    ApprovalStatus,
    ApprovalTimeoutPolicy,
)
from dataagent.infra.observability import LogNotificationSink
from dataagent.infra.runtime.workflow import InMemoryApprovalPort

ROOT = Path(__file__).resolve().parents[3]  # 仓库根


# ---------------- FakeRedis（按 Lua 首行 `-- op:` 标记分发到等价 Python 实现） ----------------
class FakeRedis:
    """最小 Redis 语义：GET/SET(PX)/DEL/INCR + eval 按 op 标记分发（不模拟真实 Lua 引擎）。"""

    def __init__(self, now_ref: dict):
        self.now_ref = now_ref
        self.kv: dict[str, tuple[str, int]] = {}  # key → (value, expire_at_ms|0)

    def _alive(self, k):
        v = self.kv.get(k)
        if v is None:
            return None
        val, exp = v
        if exp and self.now_ref["ms"] >= exp:
            self.kv.pop(k, None)
            return None
        return val

    def get(self, k):
        v = self._alive(k)
        return v.encode() if v is not None else None

    def set(self, k, v, px=None):
        self.kv[k] = (v, self.now_ref["ms"] + int(px) if px else 0)

    def delete(self, k):
        self.kv.pop(k, None)

    def incr(self, k):
        cur = int(self._alive(k) or 0) + 1
        self.set(k, str(cur))
        return cur

    def eval(self, script, numkeys, *keys_and_args):
        """与真实 Redis 对齐（真机联调取证）：Lua `return false` = nil → Python None；
        成功返回 JSON 字符串（decode_responses=True 语义）。"""
        op = script.splitlines()[0].split("op:")[1].strip()
        k, gk = keys_and_args[0], keys_and_args[1]
        owner, now_ms, ttl_ms = keys_and_args[2], int(keys_and_args[3]), int(keys_and_args[4])
        cur = self._alive(k)
        st = json.loads(cur) if cur else None
        if op == "acquire":
            if st:
                if st["owner"] == owner:
                    st["renewed_at"] = now_ms
                    self.set(k, json.dumps(st), px=ttl_ms)
                    return json.dumps(st)
                return None
            gen = self.incr(gk)
            st = {"owner": owner, "generation": gen, "renewed_at": now_ms}
            self.set(k, json.dumps(st), px=ttl_ms)
            return json.dumps(st)
        if op == "renew":
            if not st or st["owner"] != owner:
                return None
            st["renewed_at"] = now_ms
            self.set(k, json.dumps(st), px=ttl_ms)
            return "true"
        if op == "release":
            if not st or st["owner"] != owner:
                return None
            self.delete(k)
            return "true"
        if op == "takeover":
            if st:
                return None
            gen = self.incr(gk)
            st = {"owner": owner, "generation": gen, "renewed_at": now_ms}
            self.set(k, json.dumps(st), px=ttl_ms)
            return json.dumps(st)
        raise ValueError(f"unknown op {op}")


class TestRedisLeaseBackend:
    """GAP-14 生产形态：Redis 后端与内存实现同协议（Lua 原子语义经 fake 等价验证）。"""

    def _reg(self, now_ref, ttl_s=30.0):
        from services.shared.lease_backend import RedisLeaseRegistry
        # services 路径注入（dataagent 测试环境不含 root conftest）
        svc = str(ROOT / "services" / "src")
        if svc not in sys.path:
            sys.path.insert(0, svc)
        from services.shared.lease_backend import RedisLeaseRegistry as R
        return R(FakeRedis(now_ref), default_lease_s=ttl_s,
                 clock=lambda: now_ref["ms"] / 1000.0)

    def test_acquire_renew_release(self):
        now = {"ms": 0}
        reg = self._reg(now)
        st = reg.acquire("run1", "worker-a")
        assert st["generation"] == 1 and st["owner"] == "worker-a"
        now["ms"] = 10_000
        assert reg.renew("run1", "worker-a") is True
        now["ms"] = 20_000
        assert reg.release("run1", "worker-a") is True
        assert reg.generation_of("run1") == 1  # 正常流转世代不变

    def test_takeover_only_after_ttl_and_generation_increments(self):
        now = {"ms": 0}
        reg = self._reg(now, ttl_s=30.0)
        reg.acquire("run1", "worker-a")
        now["ms"] = 10_000
        with pytest.raises(PermissionError, match="租约未过期"):
            reg.takeover("run1", "worker-b")
        now["ms"] = 31_000  # TTL 过 → key 失活
        assert reg.takeover("run1", "worker-b") is True
        assert reg.generation_of("run1") == 2  # 世代持久（fencing）

    def test_owner_conflict_rejected(self):
        now = {"ms": 0}
        reg = self._reg(now)
        reg.acquire("run1", "worker-a")
        with pytest.raises(PermissionError):
            reg.acquire("run1", "worker-b")

    def test_generation_survives_expiry(self):
        """世代号计数键无 TTL：TTL 过后 generation 仍在（僵尸 Worker 自识别依据）。"""
        now = {"ms": 0}
        reg = self._reg(now)
        reg.acquire("run1", "worker-a")
        now["ms"] = 60_000
        assert reg.generation_of("run1") == 1


class TestNotificationSink:
    """GAP-19a 运营通知：升级/过期经 sink 外发（log 默认；故障 fail-safe）。"""

    def test_log_sink_records_escalate_and_expire(self):
        now = {"t": 1000.0}
        sink = LogNotificationSink()
        port = InMemoryApprovalPort(
            auto_approve=False,
            timeout_policy=ApprovalTimeoutPolicy(pending_ttl_s=100, escalate_after_s=30,
                                                 escalation_chain=("approver",)),
            clock=lambda: now["t"], sink=sink)
        port.request(ApprovalRequest(request_id="apr1", run_id="run1", action="adjust_budget",
                                     params={}, created_at=990.0))
        now["t"] = 1040.0
        port.sweep_timeouts(run_id="run1")
        now["t"] = 1105.0
        port.sweep_timeouts(run_id="run1")
        kinds = [s["kind"] for s in sink.sent]
        assert "approval_escalated:approver" in kinds and "approval_expired" in kinds

    def test_sink_failure_is_fail_safe(self):
        class BoomSink:
            def notify(self, kind, payload):
                raise RuntimeError("IM 网关挂了")

        now = {"t": 1000.0}
        port = InMemoryApprovalPort(
            auto_approve=False,
            timeout_policy=ApprovalTimeoutPolicy(pending_ttl_s=100, escalate_after_s=30,
                                                 escalation_chain=("approver",)),
            clock=lambda: now["t"], sink=BoomSink())
        port.request(ApprovalRequest(request_id="apr2", run_id="run2", action="a",
                                     params={}, created_at=990.0))
        now["t"] = 1040.0
        acts = port.sweep_timeouts(run_id="run2")  # 通知炸了巡检照常
        assert acts and acts[0][1] == "escalate:approver"


class TestValidateDeployMeta:
    """部署校验元测试：当前清单全绿（32 项硬约束）。"""

    def test_current_manifests_green(self):
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_deploy.py")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           cwd=str(ROOT))
        assert r.returncode == 0, r.stdout + r.stderr
