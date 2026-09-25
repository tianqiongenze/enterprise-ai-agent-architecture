# -*- coding: utf-8 -*-
"""EvalOps (第九篇)：企业级评测与受控进化。

- Eval Contract / 三层评测 (Outcome / Trajectory / System)
- Dataset 与 Fixture（环境快照、版本元组）
- Multi-Grader（Code / Environment / Trace / LLM）
- Batch Eval Runner + 多维 Scorecard
- Regression Gate / Canary / Kill Switch / 版本回滚
"""
from __future__ import annotations

import dataclasses
import hashlib
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol

from ...contracts.model import LlmClient
from ...contracts.runtime import Run


class OutcomeLayer:
    """Outcome：最终答案质量。"""

    def __init__(self, fn: Callable[[Run, dict], dict]):
        self.fn = fn

    def grade(self, run: Run, ref: dict) -> dict:
        return self.fn(run, ref)


@dataclass
class GraderResult:
    name: str
    score: float               # 0..1 或原始值
    passed: bool
    detail: str = ""


GraderFn = Callable[[Run, dict], GraderResult]


class Grader:
    def __init__(self, name: str, grade: GraderFn, max_score: float = 1.0):
        self.name = name
        self.grade = grade
        self.max_score = max_score


def code_grader(verify: Callable[[Run], bool], name: str = "code") -> Grader:
    """Code Grader：真实环境是否确实完成（区别于"Agent 说做了"）。"""

    def g(run: Run, ref: dict) -> GraderResult:
        ok = verify(run)
        return GraderResult(name=name, score=1.0 if ok else 0.0, passed=ok)
    return Grader(name, g, max_score=20)


def llm_grader(client: LlmClient, prompt: str, name: str = "llm") -> Grader:
    """LLM Grader：对开放任务做质量判断。"""

    def g(run: Run, ref: dict) -> GraderResult:
        from ...adapters.llm.fake_client import FakeLlmClient
        txt = fake_complete(client, prompt, run, ref)
        ok = "通过" in txt or "PASS" in txt
        return GraderResult(name=name, score=1.0 if ok else 0.5, passed=ok, detail=txt)
    return Grader(name, g, max_score=30)


def fake_complete(client: LlmClient, prompt: str, run: Run, ref: dict) -> str:
    # 演示用：真实实现由 LLM Grader 模型评分
    return "结论合理，证据链完整，通过。"


class BatchEvalRunner:
    """批量评测执行器 + 多维 Scorecard + 回归比较。"""

    def __init__(self, graders: list[Grader]):
        self.graders = graders

    def evaluate(self, cases: list[tuple[Run, dict]]) -> "EvalReport":
        per_case: list[dict] = []
        totals: dict[str, float] = {}
        max_scores: dict[str, float] = {}
        for run, ref in cases:
            row: dict[str, float] = {}
            for gr in self.graders:
                res = gr.grade(run, ref)
                row[f"{gr.name}"] = res.score
                totals[f"{gr.name}"] = totals.get(f"{gr.name}", 0) + res.score
                max_scores[f"{gr.name}"] = gr.max_score
            per_case.append(row)
        scorecard = {k: round(v / len(cases), 3) if cases else 0.0 for k, v in totals.items()}
        return EvalReport(cases=per_case, scorecard=scorecard, max_scores=max_scores)


@dataclass
class EvalReport:
    cases: list[dict]
    scorecard: dict[str, float]
    max_scores: dict[str, float]

    @property
    def mean_outcome(self) -> float:
        return self.scorecard.get("code", 0.0)

    def summary(self) -> str:
        lines = ["Eval Scorecard:"]
        for k in sorted(self.scorecard):
            lines.append(f"  {k}: {self.scorecard[k]} / {self.max_scores.get(k, 1.0)}")
        return "\n".join(lines)


class RegressionGate:
    """CI Regression Gate：平均分提升不代表可发布 —— 关键能力/安全不得退化。"""

    def __init__(self, min_scores: dict[str, float]):
        self.min_scores = min_scores

    def evaluate(self, report: EvalReport) -> tuple[bool, list[str]]:
        violations = []
        for metric, threshold in self.min_scores.items():
            got = report.scorecard.get(metric, 0.0)
            if got < threshold:
                violations.append(f"{metric}: {got} < {threshold}")
        return (len(violations) == 0), violations


class ReleaseEVolution:
    """受控进化：Canary / Kill Switch / 版本回滚。"""

    def __init__(self):
        self.canary_pct = 0.0
        self.kill_switch = False
        self.released_versions: list[str] = []

    def canary(self, percent: float) -> None:
        self.canary_pct = percent

    def promote(self, version: str) -> None:
        if not self.kill_switch:
            self.released_versions.append(version)

    def rollback(self, version: str) -> str:
        self.kill_switch = True
        return f"已触发 Kill Switch，回滚到上一版本：{version}"


def snapshot_fixture(
    *, model: str, prompt_version: str, context_version: str, tool_set: str, tenant: str
) -> dict:
    """Fixture 环境快照 + 版本元组（用于结果归因）。"""
    raw = f"{model}|{prompt_version}|{context_version}|{tool_set}|{tenant}"
    return {
        "model": model,
        "prompt_version": prompt_version,
        "context_version": context_version,
        "tool_set": tool_set,
        "tenant": tenant,
        "fingerprint": hashlib.md5(raw.encode()).hexdigest()[:12],
    }