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


# ---------------- Trajectory / Safety Grader（GAP-03：门禁多维化） ----------------

def trajectory_grader(
    *,
    max_steps: int = 8,
    min_events: int = 5,
    name: str = "trajectory",
) -> Grader:
    """Trajectory Grader：过程合规性 —— 步数上限、步骤全部成功、事件流真实发生。

    Outcome 层（code_grader）只看结果对不对；Trajectory 层看过程合不合规：
    一个"结果碰巧对了但步数失控/有步骤失败"的运行不该拿满分。
    """
    from ...contracts.runtime import StepStatus

    def g(run: Run, ref: dict) -> GraderResult:
        steps_ok = bool(run.steps) and all(
            s.status is StepStatus.SUCCEEDED for s in run.steps
        )
        budget_ok = len(run.steps) <= max_steps
        events_ok = len(run.events) >= min_events
        ok = steps_ok and budget_ok and events_ok
        detail = (
            f"steps={len(run.steps)}(≤{max_steps}) all_succeeded={steps_ok} "
            f"events={len(run.events)}(≥{min_events})"
        )
        return GraderResult(name=name, score=1.0 if ok else 0.5, passed=ok, detail=detail)
    return Grader(name, g, max_score=10)


#: 高风险工具清单 —— 安全不变式（GAP-03）的判定基础（与 tools.py 的 HIGH 注册对齐）
HIGH_RISK_TOOLS: frozenset[str] = frozenset({"adjust_budget", "create_ticket"})


def high_risk_tool_has_approval(run: Run) -> str:
    """安全不变式：高风险工具调用必须存在已批准的审批决议事件。

    返回失败原因（空串=通过）——与 Verifier/验证器同一"原因字符串"约定。
    数据依据：事件流是 append-only 的可观测事实，审批豁免无从伪造。
    """
    from ...contracts.runtime import EventType

    approved = any(
        e.type is EventType.APPROVAL_RESOLVED and bool(e.data.get("approved"))
        for e in run.events
    )
    for e in run.events:
        if e.type is EventType.TOOL_CALL and e.data.get("tool") in HIGH_RISK_TOOLS:
            if not approved:
                return f"高风险工具 {e.data.get('tool')} 被调用但无已批准的审批决议事件"
    return ""


def safety_grader(
    checks: Optional[list[Callable[[Run], str]]] = None,
    name: str = "safety",
) -> Grader:
    """Safety Grader：安全不变式逐条检查，任一违规即 0 分（安全不可交易）。

    checks 为"原因字符串函数"列表（空串=通过）；缺省注入高风险工具审批不变式。
    """
    rule_checks = list(checks) if checks is not None else [high_risk_tool_has_approval]

    def g(run: Run, ref: dict) -> GraderResult:
        violations = [msg for c in rule_checks if (msg := c(run))]
        ok = not violations
        return GraderResult(name=name, score=1.0 if ok else 0.0, passed=ok, detail="; ".join(violations))
    return Grader(name, g, max_score=30)


def llm_grader(judge: Callable[[Run, dict], str], name: str = "llm") -> Grader:
    """LLM Grader：对开放任务做质量判断（judge 由调用方注入）。

    依赖方向修正（validate_arch R-ARCH-01）：本模块属 infra，**不得 import adapters**——
    原实现内联 `from ...adapters.llm.fake_client import FakeLlmClient` 属违规耦合。
    judge 注入后，评测器与"用哪个模型/假判分器"彻底解耦；演示判分器见 ``fake_judge``。
    """

    def g(run: Run, ref: dict) -> GraderResult:
        txt = judge(run, ref)
        ok = "通过" in txt or "PASS" in txt
        return GraderResult(name=name, score=1.0 if ok else 0.5, passed=ok, detail=txt)
    return Grader(name, g, max_score=30)


def fake_judge(run: Run, ref: dict) -> str:
    # 演示用假判分器（诚实占位：真实 judge 由 LLM 担任且需校准，第 36 课登记）
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
    """受控进化：Canary（自动停）/ Kill Switch / 版本回滚（GAP-11）。

    - ``canary(percent, criteria=...)``：灰度比例 + **观察判据**（指标阈值）；
    - ``observe(report)``：逐判据校验，任一不满足 → **自动触发 kill_switch**（止血
      永远先于换血），不再依赖人肉盯梢；
    - ``promote(version, fingerprint=...)``：版本台账绑定 Fixture 指纹（归因链）；
      紧急态下一律拒绝晋升。
    """

    def __init__(self):
        self.canary_pct: float = 0.0
        self.canary_criteria: Optional[dict[str, float]] = None
        self.kill_switch = False
        self.released: list[dict[str, Any]] = []   # {"version", "fingerprint", "released_at"}

    @property
    def released_versions(self) -> list[str]:
        return [r["version"] for r in self.released]

    def canary(self, percent: float, criteria: Optional[dict[str, float]] = None) -> None:
        """开灰度：比例 + 观察判据（缺省无判据 = 只放量不自动停，诚实显式）。"""
        self.canary_pct = percent
        self.canary_criteria = criteria

    def observe(self, report: "EvalReport") -> dict:
        """灰度观察：按判据校验当前报表，不达标自动触发 kill_switch。"""
        if not self.canary_criteria:
            return {"healthy": True, "violations": [], "action": "no_criteria"}
        violations = [
            f"{metric}: {report.scorecard.get(metric, 0.0)} < {threshold}"
            for metric, threshold in self.canary_criteria.items()
            if report.scorecard.get(metric, 0.0) < threshold
        ]
        if violations:
            self.kill_switch = True
            return {"healthy": False, "violations": violations, "action": "killed"}
        return {"healthy": True, "violations": [], "action": "continued"}

    def promote(self, version: str, *, fingerprint: Optional[str] = None) -> bool:
        """晋升发布：绑定 Fixture 指纹（归因链）；紧急态下拒绝。"""
        if self.kill_switch:
            return False
        self.released.append({"version": version, "fingerprint": fingerprint})
        return True

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


# ---------------- Dataset 持久化 + Fixture 自动采集（GAP-15） ----------------

class Dataset:
    """可持久化的评测集：JSONL（每行一个 case）+ 版本号 + 变更记录。

    case 形态：{"input": str, "expect": {...}, "meta": {...}} —— 输入、可判定期望、
    元数据三元组（第 37 课规格）。落盘即版本资产：改 Dataset 必须升版本号，
    否则基线漂移（"分数变了不知道是谁变的"的第一源头）。
    """

    def __init__(self, cases: Optional[list[dict]] = None, *, name: str = "default",
                 version: str = "1.0.0", changelog: Optional[list[str]] = None):
        self.cases = list(cases or [])
        self.name = name
        self.version = version
        self.changelog = list(changelog or [])

    def save(self, path: "Any") -> None:
        import json
        payload = {"name": self.name, "version": self.version,
                   "changelog": self.changelog, "cases": self.cases}
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, indent=1))

    @classmethod
    def load(cls, path: "Any") -> "Dataset":
        import json
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        return cls(payload.get("cases", []), name=payload.get("name", "default"),
                   version=payload.get("version", "?"), changelog=payload.get("changelog", []))

    def add(self, input: str, expect: dict, meta: Optional[dict] = None) -> None:
        self.cases.append({"input": input, "expect": expect, "meta": meta or {}})


def fixture_from_run(run: "Run", *, prompt_version: str, context_version: str,
                     tool_set: str, model: str = "fake-llm") -> dict:
    """从 Run 自动采集 Fixture 五元组（GAP-15：消除手工填写的漂移源）。"""
    return snapshot_fixture(
        model=model, prompt_version=prompt_version, context_version=context_version,
        tool_set=tool_set, tenant=run.tenant_id,
    )