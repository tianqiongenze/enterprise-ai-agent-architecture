# -*- coding: utf-8 -*-
"""Memory 治理 (第八篇)：可信、可控、可审计的长期记忆。

核心设计：
- Memory ≠ Chat History ≠ Context ≠ State（边界清晰）
- MemoryPolicy：允许写入什么、是否需要确认、保存多久、谁能用
- Memory Write Pipeline：提取 → 标准化 → 校验 → 策略判断 → 写入（幂等）
- Memory Schema + Scope（用户/租户/项目/任务类型）
- Recall Contract：租户+用户+权限过滤、时效/状态过滤、分级召回排序
- 存储分层：关系存储管权限与版本、向量索引只负责召回、Evidence Store 存凭证
- MemoryOps：查看/解释/修正/删除/防投毒/多租户治理/Eval
"""
from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, Protocol


class MemoryScope(str, Enum):
    USER = "user"
    TENANT = "tenant"
    PROJECT = "project"
    TASK = "task"


class OutputChannel(str, Enum):
    ALLOWED = "allowed"
    NEEDS_CONFIRM = "needs_confirm"
    DENIED = "denied"


@dataclass
class Memory:
    """一份长期记忆。带来源、范围、权限、版本与证据。"""

    memory_id: str = field(default_factory=lambda: f"mem_{uuid.uuid4().hex[:8]}")
    scope: MemoryScope = MemoryScope.USER
    owner: str = ""            # user_id
    tenant_id: str = "default"
    key: str = ""              # 语义键
    content: str = ""
    ttl_s: Optional[float] = None
    version: int = 1
    active: bool = True
    source: str = ""           # 来源 trace/event id
    evidence_ref: str = ""     # Evidence Store 里的凭证引用
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def matches_scope(self, tenant_id: str, owner: str) -> bool:
        if self.scope == MemoryScope.TENANT:
            return tenant_id == self.tenant_id
        if self.scope == MemoryScope.USER:
            return owner == self.owner and tenant_id == self.tenant_id
        return True

    @property
    def expired(self) -> bool:
        return self.ttl_s is not None and (time.time() - self.created_at) > self.ttl_s


class MemoryStore(Protocol):
    def put(self, mem: Memory) -> None: ...
    def delete(self, memory_id: str, tenant_id: str) -> bool: ...
    def get(self, memory_id: str) -> Optional[Memory]: ...
    def search_candidates(
        self, query: str, tenant_id: str, owner: str, limit: int = 10
    ) -> list[Memory]: ...


class InMemoryMemoryStore(MemoryStore):
    def __init__(self) -> None:
        self._mem: dict[str, Memory] = {}
        self._by_owner: dict[tuple[str, str], list[str]] = {}

    def put(self, mem: Memory) -> None:
        existing = self._find_by_key(mem.tenant_id, mem.owner, mem.key)
        if existing is not None:
            # 版本治理：新版本覆盖，保留历史（此处演示仅升级版本）
            existing.content = mem.content
            existing.version += 1
            existing.updated_at = time.time()
            existing.active = True
            return
        self._mem[mem.memory_id] = mem
        self._by_owner.setdefault((mem.tenant_id, mem.owner), []).append(mem.memory_id)

    def _find_by_key(self, tenant_id, owner, key) -> Optional[Memory]:
        for mid in self._by_owner.get((tenant_id, owner), []):
            m = self._mem[mid]
            if m.key == key and m.active:
                return m
        return None

    def delete(self, memory_id: str, tenant_id: str) -> bool:
        m = self._mem.get(memory_id)
        if m is None or m.tenant_id != tenant_id:
            return False
        m.active = False  # 软删除，删除传播由 MemoryOps 处理向量索引
        return True

    def get(self, memory_id: str) -> Optional[Memory]:
        m = self._mem.get(memory_id)
        return m if m and m.active else None

    def search_candidates(self, query: str, tenant_id: str, owner: str, limit: int = 10) -> list[Memory]:
        res = [
            m for m in self._mem.values()
            if m.active and not m.expired and m.matches_scope(tenant_id, owner)
        ]
        # 简单关键词召回（真实为向量 Top-K）
        scored = []
        for m in res:
            score = 0
            for tok in re.split(r"\s+", query):
                if tok and tok.lower() in m.content.lower():
                    score += 1
            scored.append((score, m))
        scored.sort(key=lambda x: -x[0])
        return [m for _, m in scored[:limit]]


MEMORY_DENY_HINTS = ("临时结论", "原始查询结果", "模型推测", "未经验证的")


def default_memory_validate(content: str) -> tuple[bool, str]:
    """Memory 写入校验：拒绝临时结论 / 原始查询 / 模型推测。"""

    for hint in MEMORY_DENY_HINTS:
        if hint in content:
            return False, f"禁止写入: 包含'{hint}'"
    if len(content) < 4:
        return False, "内容过短"
    return True, "ok"


class MemoryPolicyEngine:
    """MemoryPolicy：什么能写、要不要确认、存多久、谁能用。"""

    def __init__(self, validate: Optional[Callable[[str], tuple[bool, str]]] = default_memory_validate):
        self.validate = validate

    def decide(self, content: str, *, proposed_scope: MemoryScope = MemoryScope.USER) -> tuple[OutputChannel, str]:
        ok, msg = self.validate(content)
        if not ok:
            return OutputChannel.DENIED, msg
        if "报告偏好" in content or "偏好" in content:
            return OutputChannel.ALLOWED, "用户明确偏好，允许写入"
        if proposed_scope == MemoryScope.USER:
            return OutputChannel.ALLOWED, "用户级记忆"
        return OutputChannel.NEEDS_CONFIRM, "建议负向确认"


class MemoryWritePipeline:
    """从 Run 事件到可信记忆：提取 → 标准化 → 校验 → 策略 → 幂等写入。"""

    def __init__(self, store: MemoryStore, policy: MemoryPolicyEngine):
        self.store = store
        self.policy = policy

    def write(
        self,
        *,
        tenant_id: str,
        owner: str,
        key: str,
        content: str,
        scope: MemoryScope = MemoryScope.USER,
        source: str = "",
        evidence_ref: str = "",
        ttl_s: Optional[float] = None,
    ) -> tuple[bool, str, Optional[Memory]]:
        channel, msg = self.policy.decide(content, proposed_scope=scope)
        if channel == OutputChannel.DENIED:
            return False, f"拒绝写入({msg})", None
        if channel == OutputChannel.NEEDS_CONFIRM:
            return False, f"需人工确认({msg})", None
        mem = Memory(
            scope=scope,
            owner=owner,
            tenant_id=tenant_id,
            key=key,
            content=content,
            ttl_s=ttl_s,
            source=source,
            evidence_ref=evidence_ref,
        )
        self.store.put(mem)
        return True, f"写入成功 {mem.memory_id}", mem


class MemoryRecall:
    """Recall Contract：让记忆只在正确 Step 进入 Context。"""

    def __init__(self, store: MemoryStore):
        self.store = store

    def recall(
        self,
        query: str,
        *,
        tenant_id: str,
        owner: str,
        role: str = "analyst",
        limit: int = 5,
    ) -> tuple[list[Memory], list[tuple[str, str]]]:
        """租户+用户+权限/时效过滤后召回；返回 (命中, 过滤原因)。"""
        filtered: list[tuple[str, str]] = []
        candidates = self.store.search_candidates(query, tenant_id, owner, limit=20)
        out: list[Memory] = []
        for m in candidates:
            if not m.matches_scope(tenant_id, owner):
                filtered.append((m.memory_id, "scope_mismatch"))
                continue
            if m.expired:
                filtered.append((m.memory_id, "expired"))
                continue
            if not m.active:
                filtered.append((m.memory_id, "inactive"))
                continue
            out.append(m)
            if len(out) >= limit:
                break
        return out, filtered


class MemoryOps:
    """MemoryOps：查看 / 解释 / 修正 / 删除传播 / 防投毒 / 多租户。"""

    def __init__(self, store: MemoryStore):
        self.store = store

    def explain(self, memory_id: str, tenant_id: str) -> Optional[dict]:
        m = self.store.get(memory_id)
        if m is None or m.tenant_id != tenant_id:
            return None
        return {
            "memory_id": m.memory_id,
            "key": m.key,
            "content": m.content,
            "scope": m.scope.value,
            "source": m.source,
            "evidence_ref": m.evidence_ref,
            "version": m.version,
            "active": m.active,
            "created_at": m.created_at,
        }

    def delete_with_propagation(self, memory_id: str, tenant_id: str) -> bool:
        removed = self.store.delete(memory_id, tenant_id)
        # 真实实现：删除主库后，还要从向量索引/缓存/下游系统移除（删除传播）
        return removed