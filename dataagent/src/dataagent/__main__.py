# -*- coding: utf-8 -*-
"""DataAgent CLI —— 用于演示与验收 (第十篇最终展示)。

离线可运行：python -m dataagent 或 dataagent-demo。
演示: 一次完整经营分析 → 打印 Run Timeline。
"""
from __future__ import annotations

import json
import sys


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    query = " ".join(argv) or "华东区本月 GMV 下滑原因诊断"
    if query in ("-h", "--help"):
        print("用法: python -m dataagent '经营分析问题'")
        return 0

    from .app.container import DataAgentContainer, default_seed

    container = DataAgentContainer(seed_orders=default_seed())
    run = container.analyze(query)
    print(f"\n=== DataAgent 经营诊断 Run: {run.run_id} 状态={run.status.value} ===")
    print(f"查询: {run.query}\n")
    for step in run.steps:
        status = step.status.value
        out = json.dumps(step.output, ensure_ascii=False)[:180]
        print(f"[{step.step_id}] {step.name}  ({status})")
        if out and out != "{}":
            print(f"    -> {out}")
    print("\n=== Run Timeline (事件流) ===")
    for evt in run.events:
        print(f"  {evt.event_id[:12]}  {evt.type.value}  step={evt.step_id or '-'}")
    print("\n诊断完成 ✅  全部离线运行，无需任何外部 API。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())