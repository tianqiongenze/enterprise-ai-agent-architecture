# -*- coding: utf-8 -*-
"""acceptance.py —— 一条命令防造假门禁（借参照工程"可执行验收命令"方法论）。

把分散的治理门禁合流为单一入口，任何一项失败退出码 1（=退回）：
  A1 资料门禁    validate_chapters 六类 + C7 验收锁（42 讲）
  A2 台账可查    GAP-01~36 全在档、无"| 未动 |"残留、状态计数打印
  A3 自评表可查  CP-01~08 恰 8 行、缺口列不得为"无"
  A4 代码测试    内核 pytest 全绿（含 defect_regressions 缺陷回归墙）
  A5 覆盖率      内核 line coverage ≥ 90%（--skip-cov 可跳过）
  A6 交付物在位  docs/00~17、README §0 诚实表、docs/16 对比打分

用法：
  python scripts/acceptance.py                # 全量
  python scripts/acceptance.py --skip-cov     # 跳过覆盖率（快速档）
退出码：0 全过；1 任一失败（逐条打印 ✗）。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "dataagent"
FAILS: list[str] = []
PASSES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASSES if ok else FAILS).append(f"{name}{(' — ' + detail) if detail else ''}")


def run(cmd: list[str] | str, cwd: Path | None = None, timeout: int = 600) -> tuple[int, str]:
    r = subprocess.run(cmd, cwd=str(cwd or ROOT), capture_output=True, text=True,
                       timeout=timeout, shell=isinstance(cmd, str))
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def a6_artifacts() -> None:
    missing = [d.name for d in sorted(ROOT.glob("docs/*.md"))
               if not re.match(r"\d{2}-", d.name) or True]
    docs = {d.name for d in (ROOT / "docs").glob("*.md")}
    need = ["00-TOGAF架构总览.md", "01-SDD规格说明书.md", "11-大纲全面复审与缺口闭合.md",
            "12-对比审计与优化重构记录.md", "14-真实环境验收记录.md", "15-性能压测报告.md",
            "16-对比分析与打分-参照dataagent-course.md", "17-capability_self_assessment.md"]
    miss = [n for n in need if n not in docs]
    check("A6 交付物在位", not miss, f"缺失 {miss}" if miss else f"docs 共 {len(docs)} 份")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    check("A6 README §0 诚实表", "## 0. 本次交付做到了什么、没做到什么" in readme)
    check("A6 docs/16 打分表在位", "加权总分" in (ROOT / "docs" / "16-对比分析与打分-参照dataagent-course.md").read_text(encoding="utf-8"))


def a2_ledger() -> None:
    text = (ROOT / "docs" / "12-对比审计与优化重构记录.md").read_text(encoding="utf-8")
    ids = set(re.findall(r"GAP-(\d{2})", text))
    check("A2 台账覆盖 ≥36 项", len(ids) >= 36, f"实得 {len(ids)} 项")
    check("A2 台账无'未动'残留", "| 未动 |" not in text)
    n_closed = len(re.findall(r"✅", text))
    check("A2 台账含关闭标记", n_closed >= 30, f"✅ × {n_closed}")


def a3_self_assessment() -> None:
    f = ROOT / "docs" / "17-capability_self_assessment.md"
    text = f.read_text(encoding="utf-8")
    n = len(re.findall(r"^\| CP-0[1-8] ", text, re.M))
    check("A3 自评 CP-01~08 恰 8 行", n == 8, f"实得 {n}")
    # 缺口列不得为"无"：逐行抽第 5 列
    bad = []
    for line in text.splitlines():
        m = re.match(r"^\| (CP-0[1-8]) .*?\|.*?\|.*?\|.*?\|(.*?)\|", line)
        if m and re.fullmatch(r"\s*无\s*", m.group(2)):
            bad.append(m.group(1))
    check("A3 缺口列不得写'无'", not bad, f"违规 {bad}" if bad else "8 项全部有缺口")


def a1_chapters() -> None:
    code, out = run([sys.executable, str(ROOT / "scripts" / "validate_chapters.py")], timeout=300)
    ok = code == 0 and "全部通过" in out
    tail = [ln for ln in out.splitlines() if ln.strip()][-1] if out.strip() else ""
    check("A1 资料门禁 validate_chapters", ok, tail[:80])


def a4_tests() -> None:
    code, out = run([sys.executable, "-m", "pytest", "-o", "addopts=", "-q"],
                    cwd=DATA, timeout=900)
    m = re.search(r"(\d+) passed", out)
    n_fail = re.search(r"(\d+) failed", out)
    ok = code == 0 and m and not n_fail
    check("A4 内核+回归墙 pytest", bool(ok), f"{m.group(1) if m else '?'} passed"
          + (f"，{n_fail.group(1)} FAILED" if n_fail else ""))


def a5_coverage(skip: bool) -> None:
    if skip:
        check("A5 覆盖率", True, "SKIP（--skip-cov）")
        return
    code, out = run([sys.executable, "-m", "coverage", "run", "--source=src/dataagent",
                     "-m", "pytest", "-o", "addopts=", "-q"], cwd=DATA, timeout=900)
    if code != 0 and "passed" not in out:
        check("A5 覆盖率", False, out[-160:])
        return
    code2, rep = run([sys.executable, "-m", "coverage", "report"], cwd=DATA, timeout=120)
    m = re.search(r"TOTAL\s+\d+\s+\d+\s+(\d+)%", rep)
    pct = int(m.group(1)) if m else -1
    check("A5 覆盖率 ≥90%", pct >= 90, f"line coverage = {pct}%")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-cov", action="store_true")
    args = ap.parse_args()

    a6_artifacts()
    a2_ledger()
    a3_self_assessment()
    a1_chapters()
    a4_tests()
    a5_coverage(args.skip_cov)

    print("=" * 72)
    print("acceptance 防造假门禁（一条命令）")
    print("=" * 72)
    for p_ in PASSES:
        print("  ✓", p_)
    for f_ in FAILS:
        print("  ✗", f_)
    print("-" * 72)
    print(f"结果：{len(PASSES)} 过 / {len(FAILS)} 败" + ("  →  退回（禁止交付）" if FAILS else "  →  放行"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())