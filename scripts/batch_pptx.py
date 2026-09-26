# -*- coding: utf-8 -*-
"""批量生成 42 章教学 PPT（easyslides academic_general 模板, direct_editable 路线）。

从 chapters/<part>/NN-*.md 提取标题/篇章/表格内容，为每章生成 deck plan：
  cover + 3 个 content（metrics_evidence / process_outcome / table_decision 轮换）+ ending = 5 页
逐章调用 easyslides build 管线产出可编辑 PPTX。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"D:/projects/企业级Agent工程架构")
SKILL = Path.home() / ".zcode/skills/easyslides"
OUT_ROOT = ROOT / "chapters" / "pptx"
TMP = Path(r"C:/Users/Lenovo/AppData/Local/Temp/es_batch")

VARIANTS = ["metrics_evidence", "process_outcome", "table_decision"]


PART_SHORT = {
    "第一篇": "AI 核心认知", "第二篇": "企业级AI Coding", "第三篇": "贯穿项目立项",
    "第四篇": "LLM 执行底座", "第五篇": "Agent Runtime", "第六篇": "上下文治理",
    "第七篇": "工具与技能", "第八篇": "Memory 治理", "第九篇": "评测与进化",
    "第十篇": "完结篇",
}


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
        # 词边界截断: 切点落在英文单词中间时回退到上一个词边界
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
    # 提取所有 markdown 表格
    tables = []
    for block in re.findall(r"((?:^\|.*\|\s*$\n?)+)", text, re.M):
        rows = [r for r in block.strip().splitlines()]
        parsed = []
        for r in rows:
            cells = [c.strip() for c in r.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                continue
            parsed.append(cells)
        if len(parsed) >= 2:
            tables.append(parsed)
    # 思考题
    ex_m = re.search(r"## 八、思考题与实战作业\s*\n\n(.+)", text, re.S)
    return {
        "file": md,
        "title": title_m.group(1).strip() if title_m else md.stem,
        "part": part_m.group(1).strip() if part_m else "",
        "code": code_m.group(1).strip() if code_m else "",
        "tables": tables,
        "exercise": (ex_m.group(1).strip()[:120] if ex_m else ""),
    }


def build_plan(ch: dict, num: str) -> dict:
    header, *rows = ch["tables"][0] if ch["tables"] else (["概念", "说明"], [["待补充", "待补充"]])
    rows = [r for r in rows if any(c for c in r)]
    slides = [
        {"page": "P01", "role": "cover", "body_variant_id": None,
         "slot_payload": {
             "LOGO": "DataAgent", "TITLE": clean(ch["title"], 26),
             "SUBTITLE": clean(f"{ch['part']} · 教学讲义", 30),
             "AUTHOR": "企业级Agent工程架构实战营", "ADVISOR": f"第{num}讲",
             "INSTITUTION": part_short(ch["part"]), "DATE": "2026-09"}},
    ]
    # S1: 概念表 → metrics_evidence(3行) 或 table_decision
    n = min(3, len(rows))
    if n >= 2 and len(header) >= 2:
        slides.append({
            "page": "P02", "role": "content", "body_variant_id": "metrics_evidence",
            "shell_payload": {
                "SECTION_NUM": num[:2], "PAGE_TITLE": clean(f"核心概念：{header[0]}", 20),
                "LOGO": "DataAgent", "KEY_MESSAGE": clean(f"{header[1]}的三个关键要点", 22),
                "SOURCE": f"课程第{num}讲", "SECTION_NAME": part_short(ch["part"])},
            "slot_payload": {
                "METRIC_01_VALUE": clean(rows[0][0], 14), "METRIC_01_LABEL": clean(rows[0][1], 16),
                "METRIC_02_VALUE": clean(rows[1][0], 14), "METRIC_02_LABEL": clean(rows[1][1], 16),
                "METRIC_03_VALUE": clean(rows[2][0], 14) if n > 2 else "—",
                "METRIC_03_LABEL": clean(rows[2][1], 16) if n > 2 else "—",
                "EVIDENCE_01_INDEX": "01", "EVIDENCE_01_LABEL": clean(rows[0][0], 12),
                "EVIDENCE_01_DETAIL": clean(rows[0][1], 20),
                "EVIDENCE_02_INDEX": "02", "EVIDENCE_02_LABEL": clean(rows[1][0], 12),
                "EVIDENCE_02_DETAIL": clean(rows[1][1], 20)}})
    elif len(header) >= 3:
        # table_decision
        sp = {"HEAD_01": clean(header[0], 10), "HEAD_02": clean(header[1], 10), "HEAD_03": clean(header[2], 10)}
        for i in range(3):
            r = rows[i] if i < len(rows) else ["—"] * 3
            for j in range(3):
                sp[f"ROW_{i+1:02d}_{j+1:02d}"] = clean(r[j] if j < len(r) else "—", 10)
        sp["CONCLUSION"] = clean("以上对比决定工程选型", 20)
        slides.append({"page": "P02", "role": "content", "body_variant_id": "table_decision",
                       "shell_payload": {"SECTION_NUM": num[:2], "PAGE_TITLE": clean(header[0], 20),
                                         "LOGO": "DataAgent", "KEY_MESSAGE": clean("从对比到选型的判断", 22),
                                         "SOURCE": f"课程第{num}讲", "SECTION_NAME": part_short(ch["part"])},
                       "slot_payload": sp})
    # S2: 机制/流程 → process_outcome（从概念表行名提炼 3 步）
    steps = [clean(rows[i][0], 8) if i < len(rows) else f"步骤{i+1}" for i in range(3)]
    bodies = [clean(rows[i][1] if i < len(rows) and len(rows[i]) > 1 else "见讲义", 24) for i in range(3)]
    slides.append({
        "page": "P03", "role": "content", "body_variant_id": "process_outcome",
        "shell_payload": {"SECTION_NUM": num[:2], "PAGE_TITLE": clean("机制与流程", 20),
                          "LOGO": "DataAgent", "KEY_MESSAGE": clean("三步走：理解→实现→验证", 22),
                          "SOURCE": f"课程第{num}讲", "SECTION_NAME": part_short(ch["part"])},
        "slot_payload": {
            "STEP_01_NUMBER": "1", "STEP_01_TITLE": clean(steps[0], 10) or "理解", "STEP_01_BODY": clean(bodies[0], 20),
            "STEP_02_NUMBER": "2", "STEP_02_TITLE": clean(steps[1], 10) or "实现", "STEP_02_BODY": clean(bodies[1], 20),
            "STEP_03_NUMBER": "3", "STEP_03_TITLE": clean(steps[2], 10) or "验证", "STEP_03_BODY": clean(bodies[2], 20),
            "SYNTHESIS": clean(f"代码落点：{ch['code']}", 34) if ch["code"] else "结合 DataAgent 代码仓库实践"}})
    # S3: 取舍矩阵 → table_decision（第二个表），否则 evidence_argument
    if len(ch["tables"]) >= 2:
        h2, *r2 = ch["tables"][1]
        r2 = [r for r in r2 if any(c for c in r)]
        sp = {"HEAD_01": clean(h2[0], 10), "HEAD_02": clean(h2[1], 10) if len(h2) > 1 else "说明",
              "HEAD_03": clean(h2[2], 10) if len(h2) > 2 else "结论"}
        for i in range(3):
            r = r2[i] if i < len(r2) else ["—"] * 3
            for j in range(3):
                sp[f"ROW_{i+1:02d}_{j+1:02d}"] = clean(r[j] if j < len(r) else "—", 10)
        sp["CONCLUSION"] = clean("候选方案 × 取舍矩阵决定架构决策", 20)
        slides.append({"page": "P04", "role": "content", "body_variant_id": "table_decision",
                       "shell_payload": {"SECTION_NUM": num[:2], "PAGE_TITLE": clean("候选方案与取舍", 20),
                                         "LOGO": "DataAgent", "KEY_MESSAGE": clean("证据驱动的架构选型", 22),
                                         "SOURCE": f"课程第{num}讲", "SECTION_NAME": part_short(ch["part"])},
                       "slot_payload": sp})
    else:
        slides.append({
            "page": "P04", "role": "content", "body_variant_id": "evidence_argument",
            "shell_payload": {"SECTION_NUM": num[:2], "PAGE_TITLE": clean("关键证据与结论", 20),
                              "LOGO": "DataAgent", "KEY_MESSAGE": clean("用证据支撑工程判断", 22),
                              "SOURCE": f"课程第{num}讲", "SECTION_NAME": part_short(ch["part"])},
            "slot_payload": {
                "EVIDENCE_01_INDEX": "01", "EVIDENCE_01_LABEL": clean(header[0], 12),
                "EVIDENCE_01_DETAIL": clean(rows[0][1] if len(rows[0]) > 1 else "见讲义", 20),
                "EVIDENCE_02_INDEX": "02", "EVIDENCE_02_LABEL": clean(rows[1][0] if len(rows) > 1 else "机制", 12),
                "EVIDENCE_02_DETAIL": clean(rows[1][1] if len(rows) > 1 and len(rows[1]) > 1 else "见讲义", 20),
                "EVIDENCE_03_INDEX": "03", "EVIDENCE_03_LABEL": "实战",
                "EVIDENCE_03_DETAIL": clean(ch["code"], 20) if ch["code"] else "DataAgent 仓库",
                "SYNTHESIS": clean(ch["exercise"], 34) if ch["exercise"] else "完成实战作业并跑通对应测试"}})
    slides.append({
        "page": "P05", "role": "ending", "body_variant_id": None,
        "slot_payload": {
            "LOGO": "DataAgent", "THANK_YOU": "本章小结",
            "ENDING_SUBTITLE": clean(ch["title"], 30),
            "CONTACT_INFO": clean(ch["exercise"], 30) if ch["exercise"] else "完成实战作业",
            "EMAIL": f"第{num}讲 · {clean(ch['part'], 10)}", "INSTITUTION": "企业级Agent工程架构实战营",
            "COPYRIGHT": "课程复现资料 · 可公开分享", "PAGE_NUM": "5"}})
    return {"schema_version": "easyslides.deck_plan.v1",
            "decisions": {"production_scheme": "direct_editable"},
            "slides": slides}


def main():
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)
    mds = sorted(p for p in ROOT.glob("chapters/part*/[0-9][0-9]-*.md"))
    print(f"chapters: {len(mds)}")
    ok, fail = [], []
    for md in mds:
        num = md.stem[:2]
        ch = parse_chapter(md)
        plan = build_plan(ch, num)
        pf = TMP / f"ch{num}_plan.json"
        json.dump(plan, open(pf, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        part_dir = md.parent.name
        out_dir = TMP / f"ch{num}_out"
        t = re.sub(r"^\d+\s*", "", ch["title"])
        t = re.sub(r'[\/:*?"<>|：]', "·", t).strip("· ")
        pptx_out = OUT_ROOT / part_dir / f"第{num}讲-{t[:22]}.pptx"
        pptx_out.parent.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, str(SKILL / "scripts" / "easyslides.py"), "build", str(pf),
               "--template", "academic_general", "--no-imagegen", "--json",
               "--out-dir", str(out_dir), "--pptx-out", str(pptx_out)]
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(SKILL), timeout=420)
        try:
            out = r.stdout.strip()
            report = json.loads(out[out.index("{"):out.rindex("}") + 1]) if "{" in out else {}
        except Exception:
            report = {"status": "error", "issues": [{"message": (r.stderr or r.stdout)[-300:]}]}
        status = report.get("status")
        if status == "pass" and pptx_out.exists():
            ok.append((num, ch["title"]))
            print(f"[ok] {num} {ch['title'][:24]}")
        else:
            msg = "; ".join(i.get("message", "") for i in report.get("issues", []))[:200]
            fail.append((num, ch["title"], msg))
            print(f"[FAIL] {num} {msg}")
    print(f"\n=== done ok={len(ok)} fail={len(fail)} ===")
    for f in fail:
        print("  FAIL", f[0], f[2][:120])
    json.dump({"ok": [o[0] for o in ok], "fail": fail},
              open(TMP / "batch_report.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()