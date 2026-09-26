# -*- coding: utf-8 -*-
"""批量生成 42 章教学 PPT v2（easyslides academic_general, direct_editable）。

R1 学习目标页(chapter shell) / R2 代码页(PIL 代码图) / R3 架构图示页(PIL 流程图)
R4 十篇十色(--theme-token 语义角色覆盖) / R5 7 页/章(6-8 页区间)

结构: 封面 → 学习目标 → 核心概念 → 架构图示 → 关键代码 → 取舍矩阵 → 小结作业
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(r"D:/projects/企业级Agent工程架构")
SKILL = Path.home() / ".zcode/skills/easyslides"
OUT_ROOT = ROOT / "chapters" / "pptx"
TMP = Path(r"C:/Users/Lenovo/AppData/Local/Temp/es_batch")
ASSETS = TMP / "assets"

# ---------- R4: 十篇十色（语义角色覆盖） ----------
PART_SCHEMES = {
    "第一篇": dict(primary="#003366", primary_dark="#001F4D", accent="#0066CC", border="#C5D3E8", surface="#F5F7FA"),
    "第二篇": dict(primary="#146B4A", primary_dark="#0C4932", accent="#2A9D8F", border="#C9DED3", surface="#F2F8F4"),
    "第三篇": dict(primary="#6B2A7A", primary_dark="#4A1C56", accent="#9B4FB0", border="#E0D0E8", surface="#F7F3F9"),
    "第四篇": dict(primary="#B45309", primary_dark="#92400E", accent="#F59E0B", border="#F0DCC0", surface="#FAF5EC"),
    "第五篇": dict(primary="#0E7490", primary_dark="#0A5568", accent="#06B6D4", border="#C8E6EF", surface="#F0F9FC"),
    "第六篇": dict(primary="#4D7C0F", primary_dark="#3F6212", accent="#84CC16", border="#E0EDC8", surface="#F7FAEC"),
    "第七篇": dict(primary="#9F1239", primary_dark="#7A0E2C", accent="#E11D48", border="#F5D0D9", surface="#FDF2F5"),
    "第八篇": dict(primary="#3730A3", primary_dark="#2B2483", accent="#6366F1", border="#D8DCF5", surface="#F3F4FD"),
    "第九篇": dict(primary="#065F46", primary_dark="#044434", accent="#10B981", border="#C8E8DA", surface="#F0FAF5"),
    "第十篇": dict(primary="#1F2937", primary_dark="#111827", accent="#4B5563", border="#D5D9E0", surface="#F4F5F7"),
}

PART_SHORT = {
    "第一篇": "AI 核心认知", "第二篇": "企业级AI Coding", "第三篇": "贯穿项目立项",
    "第四篇": "LLM 执行底座", "第五篇": "Agent Runtime", "第六篇": "上下文治理",
    "第七篇": "工具与技能", "第八篇": "Memory 治理", "第九篇": "评测与进化",
    "第十篇": "完结篇",
}


def scheme_of(part: str) -> dict:
    for k, v in PART_SCHEMES.items():
        if (part or "").startswith(k):
            return v
    return PART_SCHEMES["第十篇"]


def part_short(part: str) -> str:
    for k, v in PART_SHORT.items():
        if (part or "").startswith(k):
            return v
    return (part or "课程")[:10]


def clean(s: str, limit: int = 20) -> str:
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = s.replace("`", "").replace("｜", "·").replace("|", "·")
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > limit:
        cut = s[:limit]
        if re.search(r"[A-Za-z0-9_]$", cut) and len(s) > limit and re.match(r"[A-Za-z0-9_]", s[limit]):
            w = re.search(r"[A-Za-z0-9_]+$", cut)
            if w and w.group(0) != cut:
                cut = cut[: len(cut) - len(w.group(0))].rstrip()
        s = cut.rstrip(" ·，,")
    return s if s else "—"


def parse_chapter(md: Path) -> dict:
    text = md.read_text(encoding="utf-8")
    title_m = re.search(r"^# (.+)$", text, re.M)
    part_m = re.search(r"所属篇：(.+?)｜", text)
    code_m = re.search(r"对应代码：`(.+?)`", text)
    tables = []
    for block in re.findall(r"((?:^\|.*\|\s*$\n?)+)", text, re.M):
        parsed = []
        for r in block.strip().splitlines():
            cells = [c.strip() for c in r.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                continue
            parsed.append(cells)
        if len(parsed) >= 2:
            tables.append(parsed)
    code_block = ""
    sec = re.split(r"## (?:五、)?关键代码", text)
    if len(sec) > 1:
        m = re.search(r"```python\n(.*?)```", sec[-1], re.S)
        if m:
            code_block = m.group(1)
    ex_m = re.search(r"## 八、思考题与实战作业\s*\n\n(.+)", text, re.S)
    return {
        "file": md, "title": title_m.group(1).strip() if title_m else md.stem,
        "part": part_m.group(1).strip() if part_m else "",
        "code": code_m.group(1).strip() if code_m else "",
        "tables": tables, "code_block": code_block,
        "exercise": (ex_m.group(1).strip()[:120] if ex_m else ""),
    }


# ---------------- R2: 代码图（深色编辑器风格） ----------------
_F_CODE = ImageFont.truetype(r"C:/Windows/Fonts/consola.ttf", 26)
_F_CODE_CJK = ImageFont.truetype(r"C:/Windows/Fonts/msyh.ttc", 24)
_F_UI = ImageFont.truetype(r"C:/Windows/Fonts/msyh.ttc", 26)
_F_UI_B = ImageFont.truetype(r"C:/Windows/Fonts/msyh.ttc", 30)

KEYWORDS = {"def", "class", "from", "import", "return", "if", "else", "elif", "for",
            "while", "with", "as", "try", "except", "raise", "print", "yield", "lambda",
            "in", "not", "and", "or", "None", "True", "False", "async", "await", "pass"}


def _tok_color(line: str):
    """[(text, kind)] 片段; kind: str/cmt/None。"""
    if "#" in line:
        i = line.index("#")
        code, comment = line[:i], line[i:]
    else:
        code, comment = line, ""
    segs, buf, i, n = [], "", 0, len(code)
    while i < n:
        c = code[i]
        if c in "\"'":
            j = code.find(c, i + 1)
            j = j if j != -1 else n
            if buf:
                segs.append((buf, None)); buf = ""
            segs.append((code[i:j + 1], "str"))
            i = j + 1
            continue
        buf += c
        i += 1
    if buf:
        segs.append((buf, None))
    if comment:
        segs.append((comment, "cmt"))
    return segs


def gen_code_png(ch: dict, num: str, scheme: dict) -> Path:
    ASSETS.mkdir(parents=True, exist_ok=True)
    out = ASSETS / f"code_{num}.png"
    W, H = 1400, 820
    img = Image.new("RGB", (W, H), "#0F172A")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 64], fill="#1E293B")
    fname = Path(ch["code"]).name if ch["code"] else f"lecture_{num}.py"
    d.ellipse([24, 22, 40, 38], fill="#EF4444")
    d.ellipse([52, 22, 68, 38], fill="#F59E0B")
    d.ellipse([80, 22, 96, 38], fill="#22C55E")
    d.text((120, 17), fname, font=_F_UI, fill="#94A3B8")
    d.text((W - 150, 17), f"第{num}讲", font=_F_UI, fill=scheme["accent"])
    raw = [l for l in (ch["code_block"] or "# 本讲代码见讲义 chapters/ 对应章节").splitlines() if l.strip()][:15]
    y0 = 92 if len(raw) >= 12 else 92 + max(0, (12 - len(raw)) * 46 // 2)
    y = y0
    for idx, line in enumerate(raw, 1):
        d.text((30, y), f"{idx:>2}", font=_F_CODE, fill="#475569")
        x = 86
        if any("\u4e00" <= c <= "\u9fff" for c in line):
            d.text((x, y), line[:46], font=_F_CODE_CJK, fill="#ABB2BF")
        else:
            for seg, kind in _tok_color(line):
                color = {"str": "#98C379", "cmt": "#7F848E"}.get(kind)
                if color is None:
                    first = re.match(r"[A-Za-z_][A-Za-z0-9_]*", seg)
                    color = "#C678DD" if first and first.group(0) in KEYWORDS else "#ABB2BF"
                d.text((x, y), seg, font=_F_CODE, fill=color)
                x += int(d.textlength(seg, font=_F_CODE))
        y += 46
    if len(raw) < 6:
        d.text((86, y + 18), "... 完整代码见讲义与 dataagent/ 仓库对应模块 ...",
               font=_F_CODE_CJK, fill="#64748B")
    d.rectangle([0, H - 8, W, H], fill=scheme["primary"])
    img.save(out)
    return out


# ---------------- R3: 架构/流程图示 ----------------
def gen_diagram_png(ch: dict, num: str, scheme: dict, rows: list) -> Path:
    ASSETS.mkdir(parents=True, exist_ok=True)
    out = ASSETS / f"diag_{num}.png"
    W, H = 1400, 820
    img = Image.new("RGB", (W, H), "#FFFFFF")
    d = ImageDraw.Draw(img)
    _head = clean(ch["title"].split("：")[0], 16)
    if len(_head) < 6:
        _head = clean(ch["title"], 16).rstrip(" ·，,让每")
    d.text((60, 40), f"{_head} · 执行链路", font=_F_UI_B, fill="#1F2937")
    d.text((60, 92), f"第{num}讲 · {part_short(ch['part'])}", font=_F_UI, fill="#6B7280")
    boxes = rows[:3] if rows else [["输入", "业务问题"], ["处理", "Runtime 编排"], ["输出", "结论与行动"]]
    prim = scheme["primary"]; acc = scheme["accent"]; border = scheme["border"]
    bx, bw, bh = 260, 880, 170
    y = 150
    for i, r in enumerate(boxes):
        term = clean(r[0] if r else "步骤", 16)
        desc = clean(r[1] if len(r) > 1 else "", 34)
        d.rounded_rectangle([bx, y, bx + bw, y + bh], radius=18, fill=scheme["surface"], outline=prim, width=3)
        d.rounded_rectangle([bx, y, bx + 14, y + bh], radius=7, fill=acc)
        d.text((bx + 48, y + 28), term, font=_F_UI_B, fill=prim)
        if desc:
            d.text((bx + 48, y + 92), desc, font=_F_UI, fill="#374151")
        d.text((bx + bw - 120, y + 28), f"0{i+1}", font=_F_UI_B, fill=border)
        if i < len(boxes) - 1:
            ay0, ay1 = y + bh + 8, y + bh + 52
            d.line([bx + bw // 2, ay0, bx + bw // 2, ay1], fill=prim, width=5)
            d.polygon([(bx + bw // 2 - 14, ay1 - 16), (bx + bw // 2 + 14, ay1 - 16), (bx + bw // 2, ay1 + 6)], fill=prim)
        y += bh + 62
    d.rectangle([0, H - 8, W, H], fill=prim)
    img.save(out)
    return out


# ---------------- R1: 学习目标 ----------------
def objectives(ch: dict, rows: list) -> str:
    c1 = clean(rows[0][0], 10).rstrip(" /·，,") if rows and rows[0] else "核心概念"
    c2 = clean(rows[1][0], 10).rstrip(" /·，,") if len(rows) > 1 and rows[1] else "机制"
    c3 = Path(ch["code"]).name if ch["code"].endswith(".py") else "DataAgent"
    return f"1) 能解释{c1}的机制；2) 能对比{c2}的取舍；3) 能跑通 {c3} 对应测试"


def build_plan(ch: dict, num: str, code_png: Path, diag_png: Path) -> dict:
    header, *rows = ch["tables"][0] if ch["tables"] else (["概念", "说明"], [["待补充", "待补充"]])
    rows = [r for r in rows if any(c for c in r)]
    n = min(3, len(rows))
    sec = part_short(ch["part"])
    t = clean(re.sub(r"^\d+\s*", "", ch["title"]), 24)
    slides = [
        {"page": "P01", "role": "cover", "body_variant_id": None,
         "slot_payload": {"LOGO": "DataAgent", "TITLE": t,
                          "SUBTITLE": clean(f"{sec} · 教学讲义", 26),
                          "AUTHOR": "企业级Agent工程架构实战营", "ADVISOR": f"第{num}讲",
                          "INSTITUTION": sec, "DATE": "2026-09"}},
        {"page": "P02", "role": "chapter", "body_variant_id": None,
         "slot_payload": {"CHAPTER_NUM": num, "CHAPTER_TITLE": "学习目标 / Lernziele",
                          "CHAPTER_DESC": objectives(ch, rows),
                          "TITLE": clean(t, 22)}},
        {"page": "P03", "role": "content", "body_variant_id": "metrics_evidence",
         "shell_payload": {"SECTION_NUM": num[:2], "PAGE_TITLE": clean(f"核心概念：{header[0]}", 20),
                           "LOGO": "DataAgent", "KEY_MESSAGE": clean(f"{header[1]}的三个关键要点", 22),
                           "SOURCE": f"课程第{num}讲", "SECTION_NAME": sec},
         "slot_payload": {
             "METRIC_01_VALUE": clean(rows[0][0], 14), "METRIC_01_LABEL": clean(rows[0][1], 16),
             "METRIC_02_VALUE": clean(rows[1][0], 14) if len(rows) > 1 else "—",
             "METRIC_02_LABEL": clean(rows[1][1], 16) if len(rows) > 1 else "—",
             "METRIC_03_VALUE": clean(rows[2][0], 14) if n > 2 else "—",
             "METRIC_03_LABEL": clean(rows[2][1], 16) if n > 2 else "—",
             "EVIDENCE_01_INDEX": "01", "EVIDENCE_01_LABEL": clean(rows[0][0], 8),
             "EVIDENCE_01_DETAIL": clean(rows[0][1], 18),
             "EVIDENCE_02_INDEX": "02", "EVIDENCE_02_LABEL": clean(rows[1][0], 8) if len(rows) > 1 else "—",
             "EVIDENCE_02_DETAIL": clean(rows[1][1], 18) if len(rows) > 1 else "见讲义"}},
        {"page": "P04", "role": "content", "body_variant_id": "figure_evidence",
         "shell_payload": {"SECTION_NUM": num[:2], "PAGE_TITLE": clean("架构与执行链路", 20),
                           "LOGO": "DataAgent", "KEY_MESSAGE": clean("一图看懂本讲的机制流转", 22),
                           "SOURCE": f"课程第{num}讲", "SECTION_NAME": sec},
         "slot_payload": {"FIGURE": str(diag_png),
                          "FIGURE_CAPTION": clean("图：本讲核心对象的执行链路（由讲义表格自动生成）", 30),
                          "EVIDENCE_01": clean(f"{clean(rows[0][0], 8)}：{clean(rows[0][1], 10)}", 14),
                          "EVIDENCE_02": clean(f"{clean(rows[1][0] if len(rows) > 1 else '机制', 8)}：{clean(rows[1][1] if len(rows) > 1 else '见讲义', 10)}", 14),
                          "EVIDENCE_03": "落点：仓库验证"}},
        {"page": "P05", "role": "content", "body_variant_id": "figure_evidence",
         "shell_payload": {"SECTION_NUM": num[:2], "PAGE_TITLE": clean("关键代码", 20),
                           "LOGO": "DataAgent", "KEY_MESSAGE": clean("可运行实现与讲解一一对应", 22),
                           "SOURCE": f"课程第{num}讲", "SECTION_NAME": sec},
         "slot_payload": {"FIGURE": str(code_png),
                          "FIGURE_CAPTION": (f"代码：{Path(ch['code']).name} · {ch['code']}" if ch["code"].endswith(".py") else "代码：见讲义与 dataagent/ 仓库")[:56],
                          "EVIDENCE_01": "契约先行：接口→实现",
                          "EVIDENCE_02": "测试见 tests/",
                          "EVIDENCE_03": "离线可运行"}},
    ]
    if len(ch["tables"]) >= 2:
        h2, *r2 = ch["tables"][1]
        r2 = [r for r in r2 if any(c for c in r)]
        sp = {"HEAD_01": clean(h2[0], 12), "HEAD_02": clean(h2[1], 12) if len(h2) > 1 else "说明",
              "HEAD_03": clean(h2[2], 12) if len(h2) > 2 else "结论"}
        for i in range(3):
            r = r2[i] if i < len(r2) else ["—"] * 3
            for j in range(3):
                sp[f"ROW_{i+1:02d}_{j+1:02d}"] = clean(r[j] if j < len(r) else "—", 12)
        sp["CONCLUSION"] = clean("候选方案 × 取舍矩阵决定架构决策", 20)
        slides.append({"page": "P06", "role": "content", "body_variant_id": "table_decision",
                       "shell_payload": {"SECTION_NUM": num[:2], "PAGE_TITLE": clean("候选方案与取舍", 20),
                                         "LOGO": "DataAgent", "KEY_MESSAGE": clean("证据驱动的架构选型", 22),
                                         "SOURCE": f"课程第{num}讲", "SECTION_NAME": sec},
                       "slot_payload": sp})
    else:
        slides.append({"page": "P06", "role": "content", "body_variant_id": "evidence_argument",
                       "shell_payload": {"SECTION_NUM": num[:2], "PAGE_TITLE": clean("关键证据与结论", 20),
                                         "LOGO": "DataAgent", "KEY_MESSAGE": clean("用证据支撑工程判断", 22),
                                         "SOURCE": f"课程第{num}讲", "SECTION_NAME": sec},
                       "slot_payload": {
                           "EVIDENCE_01_INDEX": "01", "EVIDENCE_01_LABEL": clean(header[0], 12),
                           "EVIDENCE_01_DETAIL": clean(rows[0][1] if len(rows[0]) > 1 else "见讲义", 18),
                           "EVIDENCE_02_INDEX": "02", "EVIDENCE_02_LABEL": clean(rows[1][0] if len(rows) > 1 else "机制", 12),
                           "EVIDENCE_02_DETAIL": clean(rows[1][1] if len(rows) > 1 and len(rows[1]) > 1 else "见讲义", 18),
                           "EVIDENCE_03_INDEX": "03", "EVIDENCE_03_LABEL": "实战",
                           "EVIDENCE_03_DETAIL": (Path(ch["code"]).name[:16] if ch["code"].endswith(".py") else "DataAgent 仓库"),
                           "SYNTHESIS": clean(ch["exercise"], 34) if ch["exercise"] else "完成实战作业并跑通对应测试"}})
    slides.append({"page": "P07", "role": "ending", "body_variant_id": None,
                   "slot_payload": {"LOGO": "DataAgent", "THANK_YOU": "本章小结",
                                    "ENDING_SUBTITLE": clean(t, 26),
                                    "CONTACT_INFO": clean(ch["exercise"], 30) if ch["exercise"] else "完成实战作业",
                                    "EMAIL": f"第{num}讲 · {sec}", "INSTITUTION": "企业级Agent工程架构实战营",
                                    "COPYRIGHT": "课程复现资料 · 可公开分享", "PAGE_NUM": "7"}})
    return {"schema_version": "easyslides.deck_plan.v1",
            "decisions": {"production_scheme": "direct_editable"},
            "slides": slides}


def theme_args(scheme: dict) -> list:
    args = []
    for role, hexv in scheme.items():
        args += ["--theme-token", f"{role}={hexv}"]
    return args


def main():
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    mds = sorted(p for p in ROOT.glob("chapters/part*/[0-9][0-9]-*.md"))
    print(f"chapters: {len(mds)}")
    ok, fail = [], []
    for md in mds:
        num = md.stem[:2]
        ch = parse_chapter(md)
        scheme = scheme_of(ch["part"])
        rows0 = []
        if ch["tables"]:
            rows0 = [r for r in ch["tables"][0][1:] if any(c for c in r)]
        code_png = gen_code_png(ch, num, scheme)
        diag_png = gen_diagram_png(ch, num, scheme, rows0)
        plan = build_plan(ch, num, code_png, diag_png)
        pf = TMP / f"ch{num}_plan.json"
        json.dump(plan, open(pf, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        part_dir = md.parent.name
        out_dir = TMP / f"ch{num}_out"
        t = re.sub(r"^\d+\s*", "", ch["title"])
        t = re.sub(r'[\\/:*?"<>|：]', "·", t).strip("· ")
        pptx_out = OUT_ROOT / part_dir / f"第{num}讲-{t[:22]}.pptx"
        pptx_out.parent.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, str(SKILL / "scripts" / "easyslides.py"), "build", str(pf),
               "--template", "academic_general", "--no-imagegen", "--json",
               "--out-dir", str(out_dir), "--pptx-out", str(pptx_out)] + theme_args(scheme)
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(SKILL), timeout=420)
        try:
            out = r.stdout.strip()
            report = json.loads(out[out.index("{"):out.rindex("}") + 1]) if "{" in out else {}
        except Exception:
            report = {"status": "error", "issues": [{"message": (r.stderr or r.stdout)[-300:]}]}
        if report.get("status") == "pass" and pptx_out.exists():
            ok.append(num)
            print(f"[ok] {num}", flush=True)
        else:
            msg = "; ".join(i.get("message", "") for i in report.get("issues", []))[:220]
            fail.append((num, msg))
            print(f"[FAIL] {num} {msg}", flush=True)
    print(f"=== done ok={len(ok)} fail={len(fail)} ===")
    for f in fail:
        print("  FAIL", f[0], f[1][:160])
    json.dump({"ok": ok, "fail": fail}, open(TMP / "batch_report.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()