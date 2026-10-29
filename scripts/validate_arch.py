# -*- coding: utf-8 -*-
"""架构依赖方向自检（docs/13 借鉴动作：依赖规则"可机器验证"）。

规则（R-ARCH-01，五层单向）：
    app → adapters → infra → contracts ← domain
具体禁令（source 前缀 → 禁止 import 的前缀）：
    dataagent.domain.   → dataagent.{infra,adapters,app}.*        # 领域层零框架依赖
    dataagent.contracts.→ dataagent.{infra,adapters,app,domain}.* # 契约是最底层
    dataagent.infra.    → dataagent.{adapters,app}.*              # 基础设施不反向依赖
    dataagent.adapters. → dataagent.app.*                         # 适配器不碰组合根
    dataagent.app.      → （无禁令，组合根可达一切）
AST 扫描（含函数体内 import——第 38 课 eval_ops 的真实教训：动态 import 也要守规）。
相对导入按 level 还原为绝对前缀后再判。
用法：python scripts/validate_arch.py  → 退出码 0/1
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "dataagent" / "src" / "dataagent"

FORBIDDEN: dict[str, tuple[str, ...]] = {
    "dataagent.domain.": ("dataagent.infra.", "dataagent.adapters.", "dataagent.app."),
    "dataagent.contracts.": ("dataagent.infra.", "dataagent.adapters.", "dataagent.app.",
                             "dataagent.domain."),
    "dataagent.infra.": ("dataagent.adapters.", "dataagent.app."),
    "dataagent.adapters.": ("dataagent.app.",),
}


def resolve_module(node: ast.ImportFrom, module_file: Path) -> str | None:
    """ImportFrom → 绝对模块前缀（处理相对导入）。ast.Import 的平铺名也在此拼。"""
    if node.level == 0:
        return node.module or ""
    # 相对导入：level=1 表示当前包
    pkg_parts = module_file.relative_to(SRC.parent).with_suffix("").parts
    # file: dataagent/infra/metrics/eval_ops.py → parts=('dataagent','infra','metrics','eval_ops')
    up = node.level  # 每一级 '.' 回退一个包段（最后一段是模块名）
    base = list(pkg_parts[:-1])  # 去掉模块名 → 所属包链
    for _ in range(up - 1):
        if base:
            base.pop()
    prefix = ".".join(base)
    return f"{prefix}.{node.module}" if node.module else prefix


def iter_imports(tree: ast.AST, module_file: Path):
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = resolve_module(node, module_file)
            if mod:
                yield mod
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name


def check() -> list[str]:
    violations: list[str] = []
    for py in SRC.rglob("*.py"):
        rel = py.relative_to(SRC.parent).as_posix()
        mod_path = rel[:-3] if rel.endswith(".py") else rel
        mod_path = mod_path.replace("/", ".")  # 路径风格 → 点分模块名（否则规则前缀永远匹配不上）
        banned = None
        for prefix, forbids in FORBIDDEN.items():
            if mod_path == prefix.rstrip(".") or mod_path.startswith(prefix):
                banned = forbids
                break
        if banned is None:
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError as e:
            violations.append(f"{rel}: 语法错误 {e}")
            continue
        for mod in iter_imports(tree, py):
            for b in banned:
                if mod == b.rstrip(".") or mod.startswith(b):
                    violations.append(f"{rel}: import {mod} 违反依赖方向（禁止 {b}*）")
    return violations


def main() -> int:
    violations = check()
    print("=" * 72)
    print("架构依赖方向自检（R-ARCH-01）：domain→(零) contracts→(零) infra→adapters/app 禁止反向")
    print("=" * 72)
    if violations:
        for v in violations:
            print("  ✗", v)
        print(f"不通过：{len(violations)} 处违规")
        return 1
    print("全部通过 ✓（依赖方向无违规）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
