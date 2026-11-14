# -*- coding: utf-8 -*-
"""为 42 讲讲义注入/刷新可执行验收锁（参照 dataagent-course 可执行验收命令惯例）。

每讲 H1 标题后注入一行机器可查注释：
  <!-- acceptance: sections=N code=M mermaid=K lines>=L -->
- sections = "^## " 二级标题数（结构锁：删节即失败）
- code     = ```python 围栏数（代码锁）
- mermaid  = ```mermaid 围栏数（图示锁）
- lines>=L = 非空行数下限（体量锁）

期望值取自当前真实内容（基线快照）；此后任何删节/退化都会被
validate_chapters.py 的 C7 门禁拦截（内容合法增长需重跑本脚本刷新基线并注明原因）。
幂等：重复运行仅更新数值。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CH = ROOT / "chapters"
PAT = re.compile(r"<!-- acceptance: [^>]*-->\n")


def counts(text: str) -> dict:
    return {
        "sections": len(re.findall(r"^## ", text, re.M)),
        "code": len(re.findall(r"^```python", text, re.M)),
        "mermaid": len(re.findall(r"^```mermaid", text, re.M)),
        "lines": sum(1 for ln in text.splitlines() if ln.strip()),
    }


def main() -> int:
    files = sorted(CH.glob("part*/[0-9][0-9]-*.md"))
    if not files:
        print("no lectures found")
        return 1
    for f in files:
        text = f.read_text(encoding="utf-8")
        c = counts(text)
        # 体量锁 = 当前值下浮 5%（防退化同时容忍微编辑），向下取整到 5 的倍数
        lock_lines = max(50, (int(c["lines"] * 0.95) // 5) * 5)
        block = (f"<!-- acceptance: sections={c['sections']} code={c['code']} "
                 f"mermaid={c['mermaid']} lines>={lock_lines} -->\n")
        if PAT.search(text):
            text = PAT.sub("", text, count=1)
        # 注入到 H1 标题行之后
        lines = text.splitlines(keepends=True)
        idx = next((i for i, ln in enumerate(lines) if ln.startswith("# ")), 0)
        lines.insert(idx + 1, "\n" + block)
        f.write_text("".join(lines), encoding="utf-8")
        print(f"[ok] {f.parent.name}/{f.name}: sections={c['sections']} code={c['code']} "
              f"mermaid={c['mermaid']} lines>={lock_lines}")
    print(f"=== {len(files)} 讲验收锁已写入 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())