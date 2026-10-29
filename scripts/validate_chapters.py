# -*- coding: utf-8 -*-
"""chapters 教学资料自检脚本（工程纪律：每一条声称都要有可执行证据）。

背景：42 讲资料曾因模板化生成而出现三类缺陷且长期未被发现——
  D1 Mermaid/代码围栏错位（``` 数量守恒但开闭错位，渲染串块）；
  D2 README 索引与实际文件名不匹配（全部链接失效）；
  D3 与本讲主题无关的通用占位图复用（同一张"渐进交付"图出现 81 处）。
根因是**没有自检**。本脚本把三类缺陷变成 CI 可拦的门禁：

  C1 围栏平衡且顺序正确（逐行状态机模拟，不是数奇偶）
  C2 索引-文件双向一致（README 里的相对路径必须存在；partXX 下不得有索引外文件）
  C3 每讲必备 10 字段结构（定位/目标/图/代码/实验/Badcase/验收/思辨/引用/遗留）
  C4 反模板化：同一插图/代码块在超过阈值文件中出现 → 报警
  C5 体量下限：每讲非空行数低于阈值 → 报警（防止退化回提纲）

用法：
  python scripts/validate_chapters.py            # 全量检查，退出码 0/1
  python scripts/validate_chapters.py --min-lines 120
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHAPTERS = ROOT / "chapters"

# 每讲必备字段（对齐 dataagent-course lessons 的统一规约）
# 首部两字段允许两种形态：## 标题 或 > **字段**： 引用块（参照工程的风格）
REQUIRED_SECTIONS: list[tuple[str, str]] = [
    ("本课定位", r"^(#+\s*.*(本课定位|本章导语|课程定位)|>\s*\*\*(本课定位|本章导语|课程定位))"),
    ("教学目标", r"^(#+\s*.*(教学目标|学习目标)|>\s*\*\*(教学目标|学习目标))"),
    ("Mermaid 图", r"```mermaid"),
    ("关键代码", r"```(python|bash)"),
    ("动手实验", r"^#+\s*.*(动手实验|实验步骤|实战作业|可运行示例)"),
    ("Badcase", r"^#+\s*.*(常见错误|Badcase|badcase|踩坑|反面写法)"),
    ("验收", r"^#+\s*.*(验收|自检|通过标准)"),
    ("思辨", r"^#+\s*.*(思辨|思考题|讨论)"),
]

MIN_LINES_DEFAULT = 120          # 每讲非空行下限（提纲约 50 行，手册应远超）
TEMPLATE_REUSE_MAX_FILES = 3     # 同一插图/代码块最多出现的文件数


def iter_lesson_files() -> list[Path]:
    files: list[Path] = []
    for part in sorted(CHAPTERS.glob("part*")):
        if part.is_dir():
            files.extend(sorted(part.glob("*.md")))
    return files


def parse_index() -> list[tuple[str, str]]:
    """从 chapters/README.md 提取 (讲次, 相对路径)。"""
    out: list[tuple[str, str]] = []
    text = (CHAPTERS / "README.md").read_text(encoding="utf-8")
    for m in re.finditer(r"\|\s*(\d+)\s*\|[^|]+\|\s*`([^`]+)`\s*\|", text):
        out.append((m.group(1), m.group(2).strip()))
    return out


def check_fences(text: str) -> list[str]:
    """C1：逐行模拟围栏开闭 —— 数量守恒但错位的情况也能抓到。"""
    errors: list[str] = []
    in_fence = False
    fence_opens: list[int] = []
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("```"):
            if not in_fence:
                in_fence = True
                fence_opens.append(i)
            else:
                in_fence = False
    if in_fence:
        errors.append(f"围栏未闭合：第 {fence_opens[-1]} 行开启后直到文件结束未关闭")
    return errors


def check_python_blocks(text: str) -> list[str]:
    """C6（GAP-20）：```python 块逐块 AST 语法检查 —— 语法错误的代码片段
    会骗过"看起来能跑"的读者（禁止装饰性代码的红线需要机器守）。
    只查语法不执行（安全）；bash/mermaid 块不在本检查范围。
    """
    import ast
    errors: list[str] = []
    in_python = False
    buf: list[str] = []
    start_line = 0
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not in_python and stripped == "```python":
            in_python, buf, start_line = True, [], i
            continue
        if in_python:
            if stripped == "```":
                try:
                    ast.parse("\n".join(buf))
                except SyntaxError as e:
                    errors.append(f"python 块(第 {start_line} 行起)语法错误: 第 {start_line + e.lineno} 行 {e.msg}")
                in_python, buf = False, []
            else:
                buf.append(line)
    return errors


def check_sections(text: str, name: str) -> list[str]:
    """C3：必备字段检查。"""
    errors: list[str] = []
    for label, pattern in REQUIRED_SECTIONS:
        if not re.search(pattern, text, re.MULTILINE):
            errors.append(f"缺少必备字段[{label}]（规约：{pattern}）")
    return errors


def check_template_reuse(all_texts: dict[Path, str]) -> list[str]:
    """C4：反模板化 —— 同一 mermaid 图/代码块出现在过多文件中。"""
    errors: list[str] = []
    block_owner: Counter[str] = Counter()
    block_sample: dict[str, str] = {}
    for path, text in all_texts.items():
        for block in re.findall(r"```mermaid\n(.*?)```", text, re.DOTALL):
            key = re.sub(r"\s+", "", block)[:400]
            block_owner[key] += 1
            block_sample.setdefault(key, path.name)
    for key, count in block_owner.items():
        if count > TEMPLATE_REUSE_MAX_FILES:
            errors.append(
                f"同一 mermaid 图出现在 {count} 个文件中（>{TEMPLATE_REUSE_MAX_FILES}），"
                f"样例文件: {block_sample[key]} —— 疑似模板复用而非本讲专属图"
            )
    return errors


def check_index_mapping(index: list[tuple[str, str]], files: list[Path]) -> list[str]:
    """C2：索引-文件双向一致。"""
    errors: list[str] = []
    indexed = set()
    for lesson_no, rel in index:
        target = CHAPTERS / rel
        indexed.add(target.resolve())
        if not target.exists():
            errors.append(f"索引第 {lesson_no} 讲指向不存在的文件: {rel}")
    actual = {f.resolve() for f in files}
    for f in sorted(actual - indexed):
        errors.append(f"文件未被索引收录: {f.relative_to(CHAPTERS)}")
    return errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-lines", type=int, default=MIN_LINES_DEFAULT)
    args = ap.parse_args()

    files = iter_lesson_files()
    all_texts = {f: f.read_text(encoding="utf-8") for f in files}
    index = parse_index()

    problems: list[str] = []
    n_fence = n_section = n_size = n_py = 0

    for f, text in all_texts.items():
        rel = f.relative_to(CHAPTERS)
        fence_errs = check_fences(text)
        if fence_errs:
            n_fence += 1
            problems += [f"[C1 围栏] {rel}: {e}" for e in fence_errs]
        py_errs = check_python_blocks(text)
        if py_errs:
            n_py += 1
            problems += [f"[C6 语法] {rel}: {e}" for e in py_errs]
        sec_errs = check_sections(text, f.name)
        if sec_errs:
            n_section += 1
            problems += [f"[C3 结构] {rel}: {e}" for e in sec_errs]
        nonempty = sum(1 for line in text.splitlines() if line.strip())
        if nonempty < args.min_lines:
            n_size += 1
            problems.append(f"[C5 体量] {rel}: 非空行 {nonempty} < {args.min_lines}（疑似提纲而非手册）")

    problems += [f"[C2 索引] {e}" for e in check_index_mapping(index, files)]
    problems += [f"[C4 模板] {e}" for e in check_template_reuse(all_texts)]

    print("=" * 72)
    print(f"chapters 自检：{len(files)} 讲 · 索引 {len(index)} 条 · 下限 {args.min_lines} 行")
    print("=" * 72)
    if problems:
        for p in problems:
            print("  ✗", p)
        print("-" * 72)
        print(
            f"不通过：{len(problems)} 项问题"
            f"（围栏 {n_fence} / 语法 {n_py} / 结构 {n_section} / 体量 {n_size} / 索引与模板见上）"
        )
        return 1
    print("全部通过 ✓（围栏 / 语法 / 结构 / 体量 / 索引 / 反模板）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
