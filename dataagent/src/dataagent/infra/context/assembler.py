# -*- coding: utf-8 -*-
"""Context Runtime —— 面向决策步骤的最小充分、可信可控上下文 (第六篇)。

核心设计：
- 上下文 ≠ Prompt：每条信息携带来源、版本、权限、可信度、生命周期 (Context Schema)
- ContextProvider 分层：租户身份 / 任务目标 / 运行状态 / 业务知识解耦
- 硬性过滤（权限、租户、有效期）优先于软性排序 —— 不能被"高相关性"绕过
- Token Budget 分区管理；精炼保留不变量；Artifact 引用
- 关键上下文缺失时停止执行 (sufficiency gate)

Context Contract 四种 Decision Context（DataAgent 实战）：
  planning, query_design, evidence_verification, suggestion_generation
"""
from __future__ import annotations

import dataclasses
import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, Protocol

from ..security.guards import InjectionGuard

#: 模块级注入防护器（GAP-07：信任分级接入硬过滤的执行件）
_INJECTION_GUARD = InjectionGuard()


def default_token_estimator(text: str) -> int:
    """中文感知 token 估算（GAP-13）。

    旧口径 ``len(text)//4`` 对中文低估 2-4 倍（1 汉字 ≈ 1~2 token，而非 0.25）。
    新口径：CJK 字符按 1 token 计，其余按 4 字符 1 token 计——对英文与旧口径一致，
    对中文显著更接近真实 tokenizer。仍为估算：生产可注入真实 tokenizer（可插拔）。
    """
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return max(1, cjk + (other + 3) // 4)


class Provenance(str, Enum):
    SYSTEM_RULE = "system_rule"
    TENANT_ATTR = "tenant_attr"
    USER_INPUT = "user_input"
    BUSINESS_KNOWLEDGE = "business_knowledge"
    TOOL_RESULT = "tool_result"
    MEMORY = "memory"


class TrustLevel(str, Enum):
    SYSTEM = "system"
    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"


@dataclass(frozen=True)
class ContextItem:
    """统一 Context Schema：一条上下文信息的结构化载体。"""

    key: str
    content: str
    provenance: Provenance = Provenance.BUSINESS_KNOWLEDGE
    trust: TrustLevel = TrustLevel.TRUSTED
    priority: int = 10          # 数值越高越重要，必需信息优先保障
    ttl_s: Optional[float] = None  # 生命周期（当前 step 有效）
    tenant_id: str = "default"
    role_mask: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    tokens: int = 0
    created_at: float = field(default_factory=time.time)

    @property
    def expired(self) -> bool:
        return self.ttl_s is not None and (time.time() - self.created_at) > self.ttl_s


@dataclass
class ContextSlice:
    """一次组装产出的上下文切片：已包含 + 被过滤 + 预算占用。"""

    items: list[ContextItem] = field(default_factory=list)
    filtered: list[tuple[str, str]] = field(default_factory=list)  # (key, reason)
    tokens_used: int = 0
    decision_trace: list[dict[str, Any]] = field(default_factory=list)


ProviderFn = Callable[[], ContextItem | list[ContextItem] | None]


class ContextProvider:
    """一个上下文提供源：暴露键、内容、优先级和元数据。"""

    def __init__(self, key: str, fn: ProviderFn, *, priority: int = 10, provenance: Provenance = Provenance.BUSINESS_KNOWLEDGE):
        self.key = key
        self.fn = fn
        self.priority = priority
        self.provenance = provenance

    def provide(self) -> list[ContextItem]:
        got = self.fn()
        if got is None:
            return []
        if isinstance(got, ContextItem):
            return [dataclasses.replace(got, provenance=self.provenance, priority=self.priority)]
        return [
            dataclasses.replace(it, provenance=self.provenance, priority=self.priority)
            for it in got
        ]


def simple_provider(key, content, **kw):
    return ContextProvider(
        key,
        lambda: ContextItem(key=key, content=content, **kw),
        priority=kw.pop("priority", 10) if "priority" in kw else 10,
    )


class ContextAssembler:
    """动态上下文装配管线：硬过滤 → 信任接线 → 预算分区 → 排序 → 裁剪 → 充分性检查。"""

    def __init__(
        self,
        *,
        token_budget: int = 6000,
        budget_partitions: Optional[dict[str, int]] = None,
        token_estimator: Optional[Callable[[str], int]] = None,
    ):
        self.token_budget = token_budget
        # 分区：provenance 类别 -> token 上限
        self.budget_partitions = budget_partitions or {
            "system_rule": 600,
            "tenant_attr": 400,
            "user_input": 400,
            "business_knowledge": 2000,
            "tool_result": 1500,
            "memory": 700,
        }
        # token 估算可插拔（GAP-13）：默认中文感知估算，生产可注入真实 tokenizer
        self._estimate_fn = token_estimator or default_token_estimator
        self.providers: list[ContextProvider] = []

    def register(self, provider: ContextProvider) -> None:
        self.providers.append(provider)

    def assemble(
        self,
        *,
        tenant_id: str = "default",
        roles: set[str] = {"analyst"},
        hard_filter: Optional[Callable[[ContextItem], tuple[bool, str]]] = None,
        step_contract: Optional["ContextContract"] = None,
    ) -> ContextSlice:
        """组装上下文并执行充分性检查。"""
        slice_ = ContextSlice()
        partition_used: dict[str, int] = {}

        candidate_items: list[ContextItem] = []
        for p in self.providers:
            for it in p.provide():
                if it.expired:
                    slice_.filtered.append((it.key, "expired"))
                    continue
                # 硬性过滤：租户 / 角色 / 权限 / 有效期
                if it.tenant_id != "*" and it.tenant_id != tenant_id:
                    slice_.filtered.append((it.key, f"tenant_mismatch:{it.tenant_id}"))
                    continue
                if it.role_mask and not (set(it.role_mask) & roles):
                    slice_.filtered.append((it.key, "role_mismatch"))
                    continue
                # 信任分级接线（GAP-07）：UNTRUSTED 内容fail-closed 处置——
                # 注入语料直接拦截；其余自动消毒包裹（把信任边界写成文本结构）
                if it.trust is TrustLevel.UNTRUSTED:
                    if _INJECTION_GUARD.is_instruction_leak(it.content):
                        slice_.filtered.append((it.key, "instruction_leak_blocked"))
                        continue
                    it = dataclasses.replace(
                        it, content=_INJECTION_GUARD.sanitize_external(it.content)
                    )
                if hard_filter is not None:
                    ok, reason = hard_filter(it)
                    if not ok:
                        slice_.filtered.append((it.key, reason))
                        continue
                candidate_items.append(it)

        # 预算分区
        candidate_items.sort(key=lambda c: (-c.priority, len(c.content)))
        for it in candidate_items:
            tok = self._estimate(it)
            partition = self.budget_partitions.get(it.provenance.value, 300)
            if partition_used.get(it.provenance.value, 0) + tok > partition:
                slice_.filtered.append((it.key, "budget_partition_exceeded"))
                continue
            if slice_.tokens_used + tok > self.token_budget:
                slice_.filtered.append((it.key, "total_budget_exceeded"))
                continue
            if it.tokens == 0:
                # 返回新对象避免改动原件
                it = dataclasses.replace(it, tokens=tok)
            slice_.items.append(it)
            slice_.tokens_used += tok
            partition_used[it.provenance.value] = partition_used.get(it.provenance.value, 0) + tok

        # 决策追踪
        slice_.decision_trace.append({
            "ts": time.time(),
            "tenant": tenant_id,
            "candidates": len(candidate_items),
            "included": len(slice_.items),
            "filtered": len(slice_.filtered),
            "tokens": slice_.tokens_used,
        })

        if step_contract is not None:
            missing = step_contract.required_intersection(slice_)
            if missing:
                slice_.filtered.append(("__missing_required__", f"缺少必需上下文: {missing}"))
        return slice_

    def _estimate(self, it: ContextItem) -> int:
        return self._estimate_fn(it.key + it.content)


class ContextContract:
    """面向决策步骤的定义：哪些是必需、哪些允许、哪些禁止。"""

    def __init__(self, name: str, *, required: tuple[str, ...] = (), blocked: tuple[str, ...] = ()):
        self.name = name
        self.required = required
        self.blocked = blocked

    def required_intersection(self, slice_: ContextSlice) -> list[str]:
        present = {it.key for it in slice_.items}
        return [k for k in self.required if k not in present]

    def violates_blocked(self, slice_: ContextSlice) -> list[str]:
        present = {it.key for it in slice_.items}
        return [k for k in self.blocked if k in present]

    def sufficiency_ok(self, slice_: ContextSlice) -> bool:
        """充分性检查：关键上下文缺失则停止执行。"""
        return not self.required_intersection(slice_)


def render_prompt_template(slice_: ContextSlice, header: str = "") -> str:
    """把 ContextSlice 渲染成结构化的提示词（只是装配的一环）。"""
    parts = []
    if header:
        parts.append(header)
    parts.append("## 系统规则与租户信息")
    for it in slice_.items:
        if it.provenance in (Provenance.SYSTEM_RULE, Provenance.TENANT_ATTR):
            parts.append(f"- {it.content}")
    parts.append("## 决策上下文")
    for it in slice_.items:
        if it.provenance not in (Provenance.SYSTEM_RULE, Provenance.TENANT_ATTR):
            parts.append(f"- [{it.key}] {it.content}")
    return "\n".join(parts)