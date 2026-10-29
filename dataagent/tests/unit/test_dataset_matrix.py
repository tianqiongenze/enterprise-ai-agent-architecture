# -*- coding: utf-8 -*-
"""评测集覆盖矩阵（docs/13 最后一条借鉴项）+ eval 冒烟。

覆盖矩阵纪律（第 37 课）：Dataset 的判定标准不是条数，是**覆盖率**——
每个任务类型 × 每个租户 × 正反例都有代表。本测试把"覆盖矩阵"变成机器断言：
矩阵缺格 = 测试失败，防止评测集悄悄退化成"三条骨架"。
"""
import json
from pathlib import Path

import pytest

from dataagent.app.container import DataAgentContainer, default_seed
from dataagent.infra.metrics.eval_ops import (
    BatchEvalRunner,
    Dataset,
    code_grader,
    trajectory_grader,
)

DATASET = Path(__file__).resolve().parents[2] / "evals" / "dataset_v1.jsonl"


class TestDatasetCoverageMatrix:
    def test_dataset_exists_and_parses(self):
        ds = Dataset.load(DATASET)
        assert ds.name and ds.version and len(ds.cases) >= 9

    def test_task_x_tenant_matrix_full(self):
        """矩阵断言：4 任务 × 2 租户 每格都有正例。"""
        ds = Dataset.load(DATASET)
        positives = [c for c in ds.cases if c["meta"].get("kind") == "positive"]
        grid = {(c["meta"]["tenant"], c["input"]) for c in positives}
        task_inputs = {c["input"] for c in positives}
        for ten in ("ten_a", "ten_b"):
            for ti in task_inputs:
                assert (ten, ti) in grid, f"覆盖矩阵缺格: {ten} × {ti[:12]}"

    def test_negative_case_present(self):
        ds = Dataset.load(DATASET)
        negs = [c for c in ds.cases if c["meta"].get("kind") == "negative"]
        assert negs and negs[0]["expect"].get("meta_only") == "unregistered_metric"

    def test_every_case_has_judgeable_expect(self):
        """红线：无判定期望的 case = 没有验收（第 36 课三要件）。"""
        ds = Dataset.load(DATASET)
        for c in ds.cases:
            assert c.get("expect"), f"缺期望: {c['input'][:20]}"
            assert "expect_status" in c["expect"] or "meta_only" in c["expect"]


class TestEvalSmoke:
    """评测冒烟：Dataset 全量正例过容器 → 三 Grader 记分卡全过。"""

    def test_full_dataset_scores_green(self):
        ds = Dataset.load(DATASET)
        c = DataAgentContainer(seed_orders=default_seed())
        cases = []
        for case in ds.cases:
            if case["meta"].get("kind") == "negative":
                continue  # 反例为领域层解析语义（test 级已覆盖），不进 run 评测
            run = c.analyze(case["input"], case["meta"]["tenant"])
            cases.append((run, case["expect"]))
        report = BatchEvalRunner([
            code_grader(lambda r: r.status.value == "succeeded" and len(r.events) > 5),
            trajectory_grader(),
        ]).evaluate(cases)
        gate_min = {"code": 0.9, "trajectory": 0.9}
        for k, v in report.scorecard.items():
            assert v >= gate_min.get(k, 0.0), (k, report.scorecard)
        assert len(cases) == 8  # 4 任务 × 2 租户

    def test_unregistered_metric_honestly_unresolvable(self):
        """反例语义钉住：未注册指标必须"显式不可达"（第 22 课）。"""
        from dataagent.domain.analytics import InMemoryMetricRegistry, Metric
        reg = InMemoryMetricRegistry()
        reg.register(Metric(name="gmv", display_name_zh="成交总额", formula="F", aliases=("销售额",)))
        with pytest.raises(ValueError, match="未注册"):
            reg.resolve("复购率")
