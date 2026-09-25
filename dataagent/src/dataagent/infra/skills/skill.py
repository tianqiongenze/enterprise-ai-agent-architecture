# -*- coding: utf-8 -*-
"""Skill Engineering (第七篇第4课)：把一次成功的经营分析固化为领域能力。

Skill 六层结构：使命边界、领域原则、操作步骤、完成标准、验证器、产物模板。
Skill 内部由 Tool/Workflow/SubAgent 组合；渐进式加载；Skill Validator；
生命周期治理（版本、兼容性、效果回归）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class Skill:
    """领域能力固化的 Skill：使命 + 原则 + 步骤 + 标准 + 验证器 + 产物。"""

    name: str
    mission: str                     # 使命边界：这个 Skill 负责什么 / 不负责什么
    principles: list[str] = field(default_factory=list)   # 领域原则
    steps: list[str] = field(default_factory=list)        # 操作步骤
    completion_criteria: list[str] = field(default_factory=list)  # 完成标准
    version: str = "1.0.0"
    owner: str = "platform"
    requires: list[str] = field(default_factory=list)      # 依赖的工具/子 Skill
    validator: Optional[Callable[[dict], tuple[bool, str]]] = None
    prompt_fragment: str = ""        # 渐进式加载：需要用到时才注入的最小描述

    def validate(self, context: dict) -> tuple[bool, str]:
        if self.validator is not None:
            return self.validator(context)
        # 默认完成标准：所有标准都要满足
        for c in self.completion_criteria:
            if c not in context:
                return False, f"缺失完成标准: {c}"
        return True, "ok"


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        self._skills[skill.name] = skill

    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def progressive_load(self, task: str) -> list[Skill]:
        """渐进式加载：仅把与该任务相关的 Skill 最小描述注入上下文。"""
        out = []
        for name, s in self._skills.items():
            if task == "analysis" and "诊断" in s.mission:
                out.append(s)
        return out


def build_anomaly_skill(registry: SkillRegistry, strict_evidence: bool = True) -> Skill:
    """把"指标确认—假设—查询证据—验证—原因排序—生成报告"固化为 Skill。"""

    def validator(ctx: dict) -> tuple[bool, str]:
        if not ctx.get("metric_confirmed"):
            return False, "未确认指标口径"
        if not ctx.get("evidence"):
            return False, "缺少证据链"
        if strict_evidence and not ctx.get("verified"):
            return False, "证据未验证"
        return True, "ok"

    skill = Skill(
        name="anomaly_diagnosis",
        mission="经营异常诊断：负责对一个经营指标的下滑做归因与建议，不负责执行预算调整",
        principles=[
            "先确认指标口径再接触数据",
            "结论必须可追溯到证据（Claim-Evidence）",
            "资金类动作必须走人工审批，Skill 不直接执行",
        ],
        steps=[
            "指标确认",
            "提出假设",
            "查询证据",
            "分析验证",
            "原因排序",
            "生成报告",
        ],
        completion_criteria=["conclusion", "evidence", "metric_confirmed"],
        validator=validator,
        prompt_fragment="【经营异常诊断】工序：指标确认→假设→证据→验证→原因→报告。结论需附证据链。",
    )
    registry.register(skill)
    return skill