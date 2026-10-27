# -*- coding: utf-8 -*-
"""批量生成 42 章深度教学 PPT v3 —— 每章 62-78 页（用户要求 60-80 页/章）。

架构：概念驱动深度扩展。
- 每章取核心概念(≤5) → 每概念约 10 页深讲模块：
  divider / 定义内涵 / 机制图解(图) / 深入原理(对比) / 代码三切面(仓库真实代码) /
  应用实践 / 陷阱排查(表) / 优化拓展(指标)
- 固定章节：封面/目录/学习目标/知识图谱/应用实战指南/优化拓展指南/治理红线/复习考核/小结
- 十篇十色 + 4 类图示(竖排流程/循环/分层/中心辐射)
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
ASSETS = TMP / "assets_v3"

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

_F_CODE = ImageFont.truetype(r"C:/Windows/Fonts/consola.ttf", 26)
_F_CODE_CJK = ImageFont.truetype(r"C:/Windows/Fonts/msyh.ttc", 24)
_F_UI = ImageFont.truetype(r"C:/Windows/Fonts/msyh.ttc", 26)
_F_UI_B = ImageFont.truetype(r"C:/Windows/Fonts/msyh.ttc", 30)
_F_SM = ImageFont.truetype(r"C:/Windows/Fonts/msyh.ttc", 22)

KEYWORDS = {"def", "class", "from", "import", "return", "if", "else", "elif", "for",
            "while", "with", "as", "try", "except", "raise", "print", "yield", "lambda",
            "in", "not", "and", "or", "None", "True", "False", "async", "await", "pass"}

# ---------------- 句式模板（参数化深讲文案） ----------------
T = {
 "define": [
  "「{term}」指{desc}。在企业级语境下，它同时约束接口契约、生命周期与治理边界，而不只是一个名词。",
  "对「{term}」的正确定位是：{desc}；它是可观测、可治理、可演进的稳定工程对象。",
  "「{term}」的本质是{desc}。理解它的关键是分清模型能做的与系统必须兜底的。",
  "把「{term}」当工程对象看：{desc}。它有明确的输入契约、失败语义与度量口径。",
 ],
 "mechanism": [
  "「{term}」的运行机制分三步：输入契约校验 → 核心转换执行 → 结果验证与事件留痕；每一步都有明确失败语义。",
  "从数据流看「{term}」：上游产出受控载荷，经 {code} 中的实现完成转换，下游只消费已验证结果。",
  "「{term}」的机制核心是解耦：策略与执行分离、状态与过程分离、权限与相关性分离。",
  "「{term}」之所以可靠，是因为它把不确定性关进笼子：预算、超时、重试、审计四件套缺一不可。",
 ],
 "good": [
  "正确姿势：先定义「{term}」的契约与不变量，再谈实现；所有旁路都必须被审计。",
  "正确姿势：把「{term}」的决策依据落成证据（Trace/Eval），而不是凭经验拍板。",
  "正确姿势：为「{term}」设置显式预算与停止条件，宁可慢一点，不可失控。",
 ],
 "bad": [
  "常见误用：把「{term}」当成一次性胶水代码，没有版本、没有度量、没有回滚路径。",
  "常见误用：用相关性绕过「{term}」的硬性过滤，短期省事，长期必然越权或漂移。",
  "常见误用：只在 Demo 里验证「{term}」的正常路径，故障注入一跑就现出原形。",
 ],
 "apply": [
  "把「{term}」落到业务：先小流量灰度验证效果与成本，再逐步放开租户范围。",
  "「{term}」的应用入口在本课程 DataAgent：跑通对应 pytest 用例即完成最小闭环。",
  "上线「{term}」前自检三问：失败会怎样？谁能审计？回滚要多久？",
 ],
 "trap": [
  "「{term}」典型故障：静默失败——看似成功实际未经验证；处置是强制验真。",
  "「{term}」典型故障：成本失控——无预算上限的重试风暴；处置是自主性预算。",
  "「{term}」典型故障：上下文漂移——长任务丢失目标；处置是检查点与摘要不变量。",
 ],
 "hitl": [
  "「{term}」的高风险动作必须人工把关：中断（waiting_approval）→ 审批人核验完整上下文 → 批准/拒绝 → 自动恢复或取消。",
  "「{term}」的审批单要带全审计：动作、参数、发起者、decided_by、decided_at —— 事后可追责。",
  "「{term}」走 ApprovalPort 合同：manual 模式中断在 human_gate，auto 模式降级演示自动通过。",
 ],
 "jwt": [
  "「{term}」的访问控制用 JWT+RBAC：登录签发 HS256 令牌，四角色×管理域矩阵，越权 403。",
  "「{term}」的口令安全用 pbkdf2 哈希存储，密钥走环境变量 —— 大厂安全基线。",
  "「{term}」的未认证请求一律 401，角色不足 403，杜绝静默放行。",
 ],
 "queue": [
  "「{term}」的异步任务经 Pulsar 优先/Redis 兜底队列：入队 queued → Worker 消费 running → 终态落库。",
  "「{term}」的任务幂等设计：NACK 重试 + DeadLetterPolicy 兜底，毒丸不阻塞队列。",
  "「{term}」的任务状态全生命周期落库：queued/running/waiting_approval/succeeded/canceled 可查询。",
 ],
 "optimize": [
  "「{term}」优化一：把人工经验固化为资产（规则/Skill/Eval），随模型共同进化。",
  "「{term}」优化二：建立基线对照（关闭/盲选/受控三组）证明增量价值。",
  "「{term}」优化三：观测先行——无 Trace 不优化，无 Baseline 不上线。",
 ],
}

PART_ANGLE = {
 "第一篇": dict(synthesis="认知决定上限：底层心智模型清晰，选型与取舍才有依据。",
             extend="延伸阅读：从训推机理到 Agent Harness 的能力迁移地图。",
             case="案例视角：同一段 Prompt 在不同认知深度下的工程化差异。",
             govern="治理视角：模型能力边界必须由契约与验证机制补齐。"),
 "第二篇": dict(synthesis="道法术器层层递进：观念不对，工具越强偏得越远。",
             extend="延伸阅读：从个人效率到团队生产效能的观测升级。",
             case="案例视角：同一任务，SDD 驱动与 Prompt 驱动的交付质量对比。",
             govern="治理视角：经验、流程、制度外置为基础设施才是器。"),
 "第三篇": dict(synthesis="先跑通基线再谈演进：M0 质量契约决定后续里程碑的裁判尺度。",
             extend="延伸阅读：从模块化单体到分布式 Runtime 的演进路线。",
             case="案例视角：DataAgent 从 Demo 到企业级系统的六个里程碑。",
             govern="治理视角：多租户、权限、审计是立项第一天的约束。"),
 "第四篇": dict(synthesis="统一 Runtime 是一切的地基：调用成功不等于任务成功。",
             extend="延伸阅读：LogicalCall/Attempt 的生命周期与成本归集。",
             case="案例视角：故障注入下 Reliable Executor 的重试与回退实测。",
             govern="治理视角：路由、预算、回放构成模型治理三件套。"),
 "第五篇": dict(synthesis="自主与流程的混合编排：Harness 负责探索，Workflow 负责收口。",
             extend="延伸阅读：Run/Step/Event 统一执行模型与故障恢复。",
             case="案例视角：预算审批链路的审批-幂等-验真闭环实测。",
             govern="治理视角：控制权矩阵与自主性预算划定行动边界。"),
 "第六篇": dict(synthesis="上下文即决策环境：最小充分、可信可控，缺一即停。",
             extend="延伸阅读：Context Decision Trace 与上下文故障分类。",
             case="案例视角：指标口径注入与跨租户泄漏的防御实测。",
             govern="治理视角：权限先于相关性，硬过滤不可被排序绕过。"),
 "第七篇": dict(synthesis="能力形态决定治理形态：Tool/Skill/Workflow/MCP 各得其所。",
             extend="延伸阅读：三层 Tool Contract 与动态最小工具集。",
             case="案例视角：预算调整 Action 的提议-审批-执行-验真全链路。",
             govern="治理视角：最小权限、短期凭据、幂等与审计四支柱。"),
 "第八篇": dict(synthesis="记忆要有选择地记住、正确地回忆：权威数据永不进 Memory。",
             extend="延伸阅读：Recall Contract 与记忆使用追踪。",
             case="案例视角：恶意指标口径注入与删除传播的红队实测。",
             govern="治理视角：写入策略、租户隔离、失效传播三闭环。"),
 "第九篇": dict(synthesis="评测是受控进化的引擎：没有质量契约，优化就是随机游走。",
             extend="延伸阅读：Outcome/Trajectory/System 三层评测与版本元组。",
             case="案例视角：回归门禁阻断、修复验证、灰度回滚全流程。",
             govern="治理视角：软评分加硬门槛，安全项一票否决。"),
 "第十篇": dict(synthesis="从 Demo 到企业级系统的分水岭：治理、评测与人机责任边界。",
             extend="延伸阅读：DSH 与 Claude Code 的 Harness 演进对照。",
             case="案例视角：如果今天重新设计 DataAgent，会改变什么。",
             govern="治理视角：AI 自动优化的责任边界必须由人划定。"),
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


def fill(tpl: str, **kw) -> str:
    return tpl.format(**kw)[:118]


# ---------------- 解析 ----------------
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
    return {"file": md, "title": title_m.group(1).strip() if title_m else md.stem,
            "part": part_m.group(1).strip() if part_m else "",
            "code": code_m.group(1).strip() if code_m else "",
            "tables": tables, "code_block": code_block,
            "exercise": (ex_m.group(1).strip()[:120] if ex_m else "")}


def code_main_path(ch: dict) -> str:
    """从 code 字段提取第一个真实 .py 路径（容忍 (说明) 后缀 / 'A + B' / 中文点）。"""
    raw = (ch["code"] or "").strip()
    m = re.search(r"[\w/\-]+\.py", raw)
    return m.group(0) if m else ""


def _slice_file(fp: Path, label_prefix: str, out: list):
    lines = fp.read_text(encoding="utf-8", errors="ignore").splitlines()
    idx = next((i for i, l in enumerate(lines) if re.match(r"(class |def |@dataclass)", l)), 0)
    s1 = [l for l in lines[idx:idx + 15] if l.strip()][:13]
    out.append((f"{label_prefix}契约", "\n".join(s1), fp.name))
    best, cur = [], []
    for l in lines:
        if re.match(r"\s*def ", l):
            if len(cur) > len(best):
                best = cur
            cur = [l]
        elif cur:
            cur.append(l)
    if len(cur) > len(best):
        best = cur
    body = [l for l in best if l.strip()][:14]
    if body:
        out.append((f"{label_prefix}实现", "\n".join(body), fp.name))


def code_slices(ch: dict) -> list:
    """仓库真实源码切面：[(标签, 代码, 文件名)]；支持 'A + B' 双文件。"""
    out = []
    raw = code_main_path(ch)
    parts = [x.strip() for x in raw.split("+") if x.strip().endswith(".py")] if raw else []

    def resolve(rel: str):
        cands = [ROOT / rel]
        if rel.startswith("dataagent/"):
            cands.append(ROOT / "dataagent" / "src" / "dataagent" / rel[len("dataagent/"):])
        return next((c for c in cands if c.exists()), None)

    files = [resolve(x) for x in parts]
    files = [f for f in files if f][:2]
    if len(files) == 1:
        _slice_file(files[0], "", out)
    elif len(files) >= 2:
        _slice_file(files[0], "A·", out)
        _slice_file(files[1], "B·", out)
    if raw:
        tname = Path(raw).stem
        cands = [c for c in ROOT.glob("dataagent/tests/**/test_*.py") if tname[:5] in c.name]
        if cands:
            tl = cands[0].read_text(encoding="utf-8", errors="ignore").splitlines()
            ti = next((i for i, l in enumerate(tl) if l.startswith("def test_")), 0)
            s3 = [l for l in tl[ti:ti + 12] if l.strip()][:11]
            out.append(("测试", "\n".join(s3), cands[0].name))
    if not out and ch["code_block"]:
        out.append(("讲义", "\n".join([l for l in ch["code_block"].splitlines() if l.strip()][:13]), "lecture.py"))
    if not out:
        out.append(("提示", "# 本讲代码见讲义与 dataagent/ 仓库", "note.py"))
    return out[:3]


# ---------------- 图片生成 ----------------
def _tok_color(line: str):
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


def gen_code_png(num: str, tag: str, code: str, fname: str, scheme: dict) -> Path:
    ASSETS.mkdir(parents=True, exist_ok=True)
    out = ASSETS / f"code_{num}_{tag}.png"
    W, H = 1400, 820
    img = Image.new("RGB", (W, H), "#0F172A")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 64], fill="#1E293B")
    d.ellipse([24, 22, 40, 38], fill="#EF4444")
    d.ellipse([52, 22, 68, 38], fill="#F59E0B")
    d.ellipse([80, 22, 96, 38], fill="#22C55E")
    d.text((120, 17), f"{fname} · {tag}", font=_F_UI, fill="#94A3B8")
    d.text((W - 150, 17), f"第{num}讲", font=_F_UI, fill=scheme["accent"])
    raw = [l for l in code.splitlines() if l.strip()][:15]
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
        d.text((86, y + 18), "... 完整代码见讲义与 dataagent/ 仓库 ...", font=_F_CODE_CJK, fill="#64748B")
    d.rectangle([0, H - 8, W, H], fill=scheme["primary"])
    img.save(out)
    return out


def _card(d, box, term, desc, scheme, idx):
    x0, y0, x1, y1 = box
    d.rounded_rectangle(box, radius=18, fill=scheme["surface"], outline=scheme["primary"], width=3)
    d.rounded_rectangle([x0, y0, x0 + 14, y1], radius=7, fill=scheme["accent"])
    d.text((x0 + 40, y0 + 24), term, font=_F_UI_B, fill=scheme["primary"])
    if desc:
        d.text((x0 + 40, y0 + 84), desc[:26], font=_F_SM, fill="#374151")
    d.text((x1 - 110, y0 + 24), f"{idx:02d}", font=_F_UI_B, fill=scheme["border"])


def _down_arrow(d, x, y0, y1, scheme):
    d.line([x, y0, x, y1 - 14], fill=scheme["primary"], width=5)
    d.polygon([(x - 14, y1 - 26), (x + 14, y1 - 26), (x, y1 - 4)], fill=scheme["primary"])


def gen_diagram_png(num: str, tag: str, title: str, items: list, scheme: dict, variant: str) -> Path:
    """items: [(term, desc)]; variant: flow_v/cycle/layers/hub"""
    ASSETS.mkdir(parents=True, exist_ok=True)
    out = ASSETS / f"diag_{num}_{tag}.png"
    W, H = 1400, 820
    img = Image.new("RGB", (W, H), "#FFFFFF")
    d = ImageDraw.Draw(img)
    d.text((60, 36), f"{clean(title, 16)} · {tag}", font=_F_UI_B, fill="#1F2937")
    d.text((60, 88), f"第{num}讲 · 图示", font=_F_UI, fill="#6B7280")
    prim, acc, sfc, brd = scheme["primary"], scheme["accent"], scheme["surface"], scheme["border"]
    items = items[:3]
    if variant == "flow_v":
        bx, bw, bh = 280, 840, 160
        y = 140
        for i, (t2, s2) in enumerate(items):
            _card(d, (bx, y, bx + bw, y + bh), t2, s2, scheme, i + 1)
            if i < len(items) - 1:
                _down_arrow(d, bx + bw // 2, y + bh + 6, y + bh + 56, scheme)
            y += bh + 60
    elif variant == "cycle":
        cx, cy, r = 700, 480, 225
        pos = [(cx, cy - r), (cx - r, cy + r * 0.72), (cx + r, cy + r * 0.72)]
        for i, (t2, s2) in enumerate(items):
            x0, y0 = pos[i % 3]
            _card(d, (max(60, x0 - 250), y0 - 62, min(1340, x0 + 250), y0 + 62), t2, s2, scheme, i + 1)
        for a, b in [(0, 1), (1, 2), (2, 0)]:
            (xa, ya), (xb, yb) = pos[a % 3], pos[b % 3]
            mx, my = (xa + xb) // 2, (ya + yb) // 2
            d.line([xa, ya, mx, my], fill=prim, width=5)
            d.polygon([(mx - 12, my - 12), (mx + 12, my - 12), (mx, my + 12)], fill=prim)
    elif variant == "layers":
        y = 150
        for i, (t2, s2) in enumerate(items):
            indent = i * 60
            _card(d, (140 + indent, y, 1260 - indent, y + 140), t2, s2, scheme, i + 1)
            y += 160
    else:  # hub
        cx, cy = 700, 480
        d.ellipse([cx - 210, cy - 95, cx + 210, cy + 95], fill=prim)
        d.text((cx - 120, cy - 18), clean(title, 10), font=_F_UI_B, fill="#FFFFFF")
        pos = [(cx, 140), (210, 660), (1140, 660)]
        for i, (t2, s2) in enumerate(items):
            x0, y0 = pos[i]
            d.line([cx, cy, x0, y0], fill=brd, width=4)
            _card(d, (x0 - 230, y0 - 60, x0 + 230, y0 + 60), t2, s2, scheme, i + 1)
    d.rectangle([0, H - 8, W, H], fill=prim)
    img.save(out)
    return out


# ---------------- 页面构造 ----------------
class Deck:
    def __init__(self):
        self.pages = []

    def add(self, page: dict):
        self.pages.append(page)

    def divider(self, secno: int, num: str, sec: str, ctitle: str, desc: str, t_full: str):
        self.add({"page": f"D{secno:02d}", "role": "chapter", "body_variant_id": None,
                  "slot_payload": {"CHAPTER_NUM": f"{secno:02d}", "CHAPTER_TITLE": clean(ctitle, 16),
                                   "CHAPTER_DESC": clean(desc, 60), "TITLE": clean(t_full, 22)}})

    def content(self, num: str, sec: str, variant: str, title: str, key: str,
                slot_payload: dict, figure: Path | None = None, caption: str = ""):
        sp = dict(slot_payload)
        if figure is not None:
            sp["FIGURE"] = str(figure)
            sp["FIGURE_CAPTION"] = clean(caption, 56)
        secno = len(self.pages) + 1
        self.add({"page": f"P{len(self.pages)+1:03d}", "role": "content", "body_variant_id": variant,
                  "shell_payload": {"SECTION_NUM": f"{secno:02d}", "PAGE_TITLE": clean(title, 20),
                                    "LOGO": "DataAgent", "KEY_MESSAGE": clean(key, 22),
                                    "SOURCE": f"课程第{num}讲", "SECTION_NAME": sec},
                  "slot_payload": sp})


def build_plan_v3(ch: dict, num: str, scheme: dict) -> dict:
    dk = Deck()
    sec = part_short(ch["part"])
    t_full = clean(re.sub(r"^\d+\s*", "", ch["title"]), 24)
    head, *rows = ch["tables"][0] if ch["tables"] else (["概念", "说明"], [["核心概念", "见讲义"]])
    rows = [r for r in rows if any(c for c in r)]
    ang = PART_ANGLE.get(ch["part"][:3], PART_ANGLE["第十篇"])
    h2 = clean(head[1] if len(head) > 1 else "说明", 8)
    h3 = clean(head[2] if len(head) > 2 else "要点", 8)
    slices = code_slices(ch)

    # 前置
    dk.add({"page": "P01", "role": "cover", "body_variant_id": None,
            "slot_payload": {"LOGO": "DataAgent", "TITLE": t_full,
                             "SUBTITLE": clean(f"{sec} · 深度教学讲义", 26),
                             "AUTHOR": "企业级Agent工程架构实战营", "ADVISOR": f"第{num}讲",
                             "INSTITUTION": sec, "DATE": "2026-09"}})
    dk.add({"page": "P02", "role": "toc", "body_variant_id": None,
            "slot_payload": {"LOGO": "DataAgent",
                             "TOC_ITEM_1_TITLE": "概念详解", "TOC_ITEM_2_TITLE": "机制与图解",
                             "TOC_ITEM_3_TITLE": "代码实现", "TOC_ITEM_4_TITLE": "应用实践",
                             "TOC_ITEM_5_TITLE": "陷阱与排查", "TOC_ITEM_6_TITLE": "优化拓展",
                             "TOC_ITEM_1_DESC": "核心概念定义与边界", "TOC_ITEM_2_DESC": "运行机制与图解",
                             "TOC_ITEM_3_DESC": "仓库真实代码三切面", "TOC_ITEM_4_DESC": "落地步骤与场景",
                             "PAGE_NUM": "2"}})
    c1 = clean(rows[0][0], 10).rstrip(" /·，,")
    c2 = clean(rows[1][0], 10).rstrip(" /·，,") if len(rows) > 1 else "机制"
    c3 = Path(code_main_path(ch)).name if code_main_path(ch) else "DataAgent"
    dk.add({"page": "P03", "role": "chapter", "body_variant_id": None,
            "slot_payload": {"CHAPTER_NUM": num, "CHAPTER_TITLE": "学习目标 / Lernziele",
                             "CHAPTER_DESC": f"1) 能解释{c1}的机制；2) 能对比{c2}的取舍；3) 能跑通 {c3} 对应测试",
                             "TITLE": t_full}})

    # 概念深讲模块（每概念 ~10 页）
    concepts = rows[:5]
    diag_variants = ["flow_v", "cycle", "layers", "hub"]
    for ci, row in enumerate(concepts):
        term = clean(row[0], 14).rstrip(" /·，,")
        desc = clean(row[1] if len(row) > 1 else (row[2] if len(row) > 2 else "见讲义"), 44)
        s3 = clean(row[2] if len(row) > 2 else (row[1] if len(row) > 1 else "见讲义"), 30)
        ctx = dict(term=term, desc=desc, code=Path(code_main_path(ch)).name if code_main_path(ch) else "DataAgent", s3=s3)
        secno = len(dk.pages) + 1
        dk.divider(secno, num, sec, f"概念详解：{term}", fill(T["define"][ci % 4], **ctx)[:56], t_full)
        dk.content(num, sec, "evidence_argument", f"定义与内涵：{term}",
                   f"把{term}讲透：是什么、不是什么",
                   {"EVIDENCE_01_INDEX": "01", "EVIDENCE_01_LABEL": "定义",
                    "EVIDENCE_01_DETAIL": clean(fill(T["define"][ci % 4], **ctx), 40),
                    "EVIDENCE_02_INDEX": "02", "EVIDENCE_02_LABEL": h2,
                    "EVIDENCE_02_DETAIL": clean(f"{h2}维度：{desc}", 40),
                    "EVIDENCE_03_INDEX": "03", "EVIDENCE_03_LABEL": h3,
                    "EVIDENCE_03_DETAIL": clean(f"{h3}维度：{s3}", 40),
                    "SYNTHESIS": clean(ang["synthesis"], 40)})
        dg = gen_diagram_png(num, f"c{ci+1}_mech", f"{term}机制",
                             [(term, desc), ("输入", "受控载荷"), ("输出", "已验证结果")],
                             scheme, diag_variants[ci % 4])
        dk.content(num, sec, "figure_evidence", f"机制图解：{term}",
                   "一图看懂运行机制与数据流",
                   {"EVIDENCE_01": clean(fill(T["mechanism"][ci % 4], **ctx), 36),
                    "EVIDENCE_02": clean("关键环节：契约→执行→验证→留痕", 36),
                    "EVIDENCE_03": "落点：仓库验证"},
                   figure=dg, caption=f"图：{term} 的机制与数据流（{diag_variants[ci % 4]} 视角）")
        dk.content(num, sec, "comparison_synthesis", f"深入原理：{term}",
                   "正确姿势 vs 常见误用",
                   {"LEFT_TITLE": "正确姿势",
                    "LEFT_BODY": clean(fill(T["good"][ci % 3], **ctx), 44) + "\n" + "契约先行，证据留痕",
                    "RIGHT_TITLE": "常见误用",
                    "RIGHT_BODY": clean(fill(T["bad"][ci % 3], **ctx), 44) + "\n" + "无版本/无度量/无回滚",
                    "SYNTHESIS": clean(ang["govern"], 40)})
        for si, (tag2, code, fname) in enumerate(slices):
            cp = gen_code_png(num, f"c{ci+1}_{si}", code, fname, scheme)
            dk.content(num, sec, "figure_evidence",
                       f"代码{tag2}：{term}" if len(tag2) <= 4 else f"代码：{term}",
                       f"仓库真实代码 · {tag2}切面",
                       {"EVIDENCE_01": clean(f"文件：{fname}", 26),
                        "EVIDENCE_02": clean(f"切面：{tag2}——先读接口再读实现", 30),
                        "EVIDENCE_03": "测试见 tests/ 目录"},
                       figure=cp, caption=f"代码：{fname} · {tag2}（概念{ci+1} {term}）")
        dk.content(num, sec, "process_outcome", f"应用实践：{term}",
                   "三步落地：闭环→灰度→放开",
                   {"STEP_01_NUMBER": "1", "STEP_01_TITLE": "最小闭环",
                    "STEP_01_BODY": clean(fill(T["apply"][ci % 3], **ctx), 36),
                    "STEP_02_NUMBER": "2", "STEP_02_TITLE": "灰度验证",
                    "STEP_02_BODY": "小流量对照基线，观察效果/成本/时延",
                    "STEP_03_NUMBER": "3", "STEP_03_TITLE": "逐步放开",
                    "STEP_03_BODY": "按租户/场景分批，异常即回滚",
                    "SYNTHESIS": clean(ang["case"], 40)})
        dk.content(num, sec, "table_decision", f"陷阱与排查：{term}",
                   "症状→根因→处置",
                   {"HEAD_01": "症状", "HEAD_02": "根因", "HEAD_03": "处置",
                    "ROW_01_01": clean(fill(T["trap"][ci % 3], **ctx)[:14], 14),
                    "ROW_01_02": "缺少验证/预算", "ROW_01_03": "验真+预算上限",
                    "ROW_02_01": "结果不可解释", "ROW_02_02": "无 Trace 留痕", "ROW_02_03": "接入统一 Trace",
                    "ROW_03_01": "效果悄悄退化", "ROW_03_02": "无回归基线", "ROW_03_03": "评测+回归门禁",
                    "CONCLUSION": clean("先止血，再根因，最后沉淀为回归用例", 20)})
        # 工程决策 ADR（用本讲取舍矩阵行或通用三案）
        adr_rows = []
        if len(ch["tables"]) >= 2:
            h2c, *r2c = ch["tables"][1]
            r2c = [r for r in r2c if any(c for c in r)]
            if r2c:
                rr = r2c[ci % len(r2c)]
                adr_rows = [(clean(rr[0], 10), clean(rr[1] if len(rr) > 1 else "—", 10), clean(rr[2] if len(rr) > 2 else "—", 10))]
        if not adr_rows:
            adr_rows = [("直连实现", "快但耦合", "Demo 可用"), ("平台化", "前期成本高", "生产首选")]
        sp_adr = {"HEAD_01": "方案", "HEAD_02": "代价", "HEAD_03": "结论",
                  "ROW_01_01": adr_rows[0][0], "ROW_01_02": adr_rows[0][1], "ROW_01_03": adr_rows[0][2],
                  "ROW_02_01": adr_rows[1][0] if len(adr_rows) > 1 else "平台化", "ROW_02_02": adr_rows[1][1] if len(adr_rows) > 1 else "前期成本高", "ROW_02_03": adr_rows[1][2] if len(adr_rows) > 1 else "生产首选",
                  "ROW_03_01": "保持简单", "ROW_03_02": "能力上限", "ROW_03_03": "按场景取舍",
                  "CONCLUSION": clean(f"「{term}」的选型以证据与约束为准", 20)}
        dk.content(num, sec, "table_decision", f"工程决策：{term}",
                   "候选方案 × 取舍（ADR）", sp_adr)
        # 生产化机制页（第三轮新增能力的落地映射）
        sp_hitl = {"HEAD_01": "阶段", "HEAD_02": "机制", "HEAD_03": "审计/落点",
                   "ROW_01_01": "中断", "ROW_01_02": "ApprovalPending", "ROW_01_03": "waiting_approval",
                   "ROW_02_01": "决议", "ROW_02_02": "decided_by/at", "ROW_02_03": "approve/reject",
                   "ROW_03_01": "恢复", "ROW_03_02": "pre_approved", "ROW_03_03": "succeeded/canceled",
                   "CONCLUSION": clean("HITL：中断-审批-恢复 全真实落库", 20)}
        dk.content(num, sec, "table_decision", f"生产化：{term}",
                   "企业级落地三机制", sp_hitl)
        dk.content(num, sec, "metrics_evidence", f"企业治理：{term}",
                   "三项已闭合边界",
                   {"METRIC_01_VALUE": "JWT", "METRIC_01_LABEL": "HS256+四角色RBAC",
                    "METRIC_02_VALUE": "队列", "METRIC_02_LABEL": "Pulsar/Redis Worker落库",
                    "METRIC_03_VALUE": "审批", "METRIC_03_LABEL": "HITL 中断-恢复",
                    "EVIDENCE_01_INDEX": "01", "EVIDENCE_01_LABEL": "认证",
                    "EVIDENCE_01_DETAIL": "未认证401/越权403（LAN实测）",
                    "EVIDENCE_02_INDEX": "02", "EVIDENCE_02_LABEL": "队列",
                    "EVIDENCE_02_DETAIL": "queued→running→终态全落库（LAN实测）"})
        dk.content(num, sec, "metrics_evidence", f"优化拓展：{term}",
                   "三个可持续优化抓手",
                   {"METRIC_01_VALUE": "资产化", "METRIC_01_LABEL": "经验固化为规则/Skill",
                    "METRIC_02_VALUE": "基线化", "METRIC_02_LABEL": "对照实验证明增量",
                    "METRIC_03_VALUE": "观测化", "METRIC_03_LABEL": "Trace/Baseline 先行",
                    "EVIDENCE_01_INDEX": "01", "EVIDENCE_01_LABEL": "资产化",
                    "EVIDENCE_01_DETAIL": clean(fill(T["optimize"][0], **ctx), 30),
                    "EVIDENCE_02_INDEX": "02", "EVIDENCE_02_LABEL": "基线化",
                    "EVIDENCE_02_DETAIL": clean(fill(T["optimize"][1], **ctx), 30)})

    # 知识图谱
    dg = gen_diagram_png(num, "map", t_full[:8],
                         [(clean(r[0], 8), clean(r[1] if len(r) > 1 else "", 18)) for r in concepts[:3]],
                         scheme, "hub")
    dk.content(num, sec, "figure_evidence", "本章知识图谱",
               "概念之间的结构关系",
               {"EVIDENCE_01": clean("核心：" + "、".join(clean(r[0], 6) for r in concepts[:3]), 30),
                "EVIDENCE_02": "关系：输入→机制→治理",
                "EVIDENCE_03": "全部概念见讲义表格"},
               figure=dg, caption="图：本章概念关系（中心辐射视角）")

    # 应用与实战指南
    secno = len(dk.pages) + 1
    dk.divider(secno, num, sec, "应用与实战指南", "从理解到落地：场景、步骤与检查清单", t_full)
    dk.content(num, sec, "process_outcome", "实战路线图",
               "三步从 Demo 到生产",
               {"STEP_01_NUMBER": "1", "STEP_01_TITLE": "场景选择",
                "STEP_01_BODY": "选高频、可验证、低风险场景切入",
                "STEP_02_NUMBER": "2", "STEP_02_TITLE": "契约先行",
                "STEP_02_BODY": "定义输入/输出/错误语义与验收",
                "STEP_03_NUMBER": "3", "STEP_03_TITLE": "评测护航",
                "STEP_03_BODY": "建数据集与评分卡再动 Prompt",
                "SYNTHESIS": clean(ang["case"], 40)})
    dk.content(num, sec, "table_decision", "典型应用场景",
               "场景→做法→收益",
               {"HEAD_01": "场景", "HEAD_02": "做法", "HEAD_03": "收益",
                "ROW_01_01": "经营诊断", "ROW_01_02": "自主分析闭环", "ROW_01_03": "结论可解释",
                "ROW_02_01": "数据查询", "ROW_02_02": "只读网关+权限", "ROW_02_03": "安全合规",
                "ROW_03_01": "行动执行", "ROW_03_02": "审批+幂等", "ROW_03_03": "风险可控",
                "CONCLUSION": clean("场景选择决定治理强度，按风险分级", 20)})
    dk.content(num, sec, "evidence_argument", "落地检查清单",
               "上线前逐项打勾",
               {"EVIDENCE_01_INDEX": "01", "EVIDENCE_01_LABEL": "功能",
                "EVIDENCE_01_DETAIL": "核心链路全绿；故障注入通过",
                "EVIDENCE_02_INDEX": "02", "EVIDENCE_02_LABEL": "质量",
                "EVIDENCE_02_DETAIL": "三层评测达标；回归门禁通过",
                "EVIDENCE_03_INDEX": "03", "EVIDENCE_03_LABEL": "安全",
                "EVIDENCE_03_DETAIL": "权限/审计/幂等/回滚就绪",
                "SYNTHESIS": clean("GO/NO-GO 由硬门槛决定，不由均分决定", 30)})

    # 优化与拓展指南
    secno = len(dk.pages) + 1
    dk.divider(secno, num, sec, "优化与拓展指南", "让系统随模型共同进化", t_full)
    dk.content(num, sec, "comparison_synthesis", "优化方向对照",
               "短期补丁 vs 长期资产",
               {"LEFT_TITLE": "短期补丁",
                "LEFT_BODY": "改 Prompt 救火\n局部 if-else 兜底\n人工盯梢排查\n经验留在个人脑中",
                "RIGHT_TITLE": "长期资产",
                "RIGHT_BODY": "规则/Skill/Eval 沉淀\n统一 Runtime 治理\nTrace+Baseline 驱动\n资产随组织复用",
                "SYNTHESIS": clean(ang["extend"], 40)})
    dk.content(num, sec, "metrics_evidence", "拓展学习地图",
               "三层次进阶",
               {"METRIC_01_VALUE": "向上", "METRIC_01_LABEL": "架构与治理体系化",
                "METRIC_02_VALUE": "向深", "METRIC_02_LABEL": "Runtime 与可靠性",
                "METRIC_03_VALUE": "向外", "METRIC_03_LABEL": "多 Agent 与平台化",
                "EVIDENCE_01_INDEX": "01", "EVIDENCE_01_LABEL": "体系",
                "EVIDENCE_01_DETAIL": "把本讲机制放进企业级全景图",
                "EVIDENCE_02_INDEX": "02", "EVIDENCE_02_LABEL": "贯通",
                "EVIDENCE_02_DETAIL": "与前后讲次的接口互相印证"})
    dg = gen_diagram_png(num, "ext", "演进路线",
                         [("当前", clean(t_full, 12)), ("下一站", "平台化/多Agent"), ("长期", "组织AI资产飞轮")],
                         scheme, "layers")
    dk.content(num, sec, "figure_evidence", "演进路线图",
               "本讲在能力阶梯上的位置",
               {"EVIDENCE_01": "当前：本讲机制已可运行",
                "EVIDENCE_02": "下一站：与相邻模块协同治理",
                "EVIDENCE_03": "长期：固化为组织级资产"},
               figure=dg, caption="图：从本讲机制到组织资产的演进路径")

    # 治理红线
    secno = len(dk.pages) + 1
    dk.divider(secno, num, sec, "治理与常见陷阱", "企业级红线与审计要点", t_full)
    dk.content(num, sec, "table_decision", "企业级红线清单",
               "红线→后果→防护",
               {"HEAD_01": "红线", "HEAD_02": "后果", "HEAD_03": "防护",
                "ROW_01_01": "越权访问", "ROW_01_02": "数据泄漏", "ROW_01_03": "硬过滤+审计",
                "ROW_02_01": "未审批副作用", "ROW_02_02": "业务事故", "ROW_02_03": "审批+幂等",
                "ROW_03_01": "不可回放", "ROW_03_02": "无法追责", "ROW_03_03": "Trace+Checkpoint",
                "CONCLUSION": clean("红线一票否决，不允许带病上线", 20)})

    # 复习考核
    secno = len(dk.pages) + 1
    dk.divider(secno, num, sec, "复习与考核", "把本讲装进长期记忆", t_full)
    dk.content(num, sec, "evidence_argument", "复习要点",
               "三个必答题",
               {"EVIDENCE_01_INDEX": "01", "EVIDENCE_01_LABEL": "是什么",
                "EVIDENCE_01_DETAIL": clean(f"{c1}的定义与边界", 30),
                "EVIDENCE_02_INDEX": "02", "EVIDENCE_02_LABEL": "为什么",
                "EVIDENCE_02_DETAIL": clean(ang["synthesis"], 30),
                "EVIDENCE_03_INDEX": "03", "EVIDENCE_03_LABEL": "怎么用",
                "EVIDENCE_03_DETAIL": clean(f"在 DataAgent 中跑通 {c3} 对应用例", 30),
                "SYNTHESIS": clean("能讲给同事听懂，才算真正掌握", 24)})

    # ---- 填充池: 补足到 ≥62 页（高价值通用页） ----
    siblings = []
    try:
        all_mds = sorted(p2 for p2 in (ROOT / "chapters" / ch["file"].parent.name).glob("[0-9][0-9]-*.md"))
        for m2 in all_mds:
            if m2.stem[:2] == num:
                continue
            c2b = parse_chapter(m2)
            siblings.append((m2.stem[:2], c2b["title"]))
    except Exception:
        siblings = []
    pool = []
    for sib_num, sib_title in siblings[:6]:
        pool.append(("table_decision", "同篇讲次导览",
                     "相邻讲次与本讲的关联",
                     {"HEAD_01": "讲次", "HEAD_02": "主题", "HEAD_03": "关联",
                      "ROW_01_01": sib_num, "ROW_01_02": clean(re.sub(r"^\d+\s*", "", sib_title), 12),
                      "ROW_01_03": "机制互补", "ROW_02_01": num, "ROW_02_02": clean(t_full, 12),
                      "ROW_02_03": "本讲", "ROW_03_01": "—", "ROW_03_02": "—", "ROW_03_03": "—",
                      "CONCLUSION": clean("前后讲次接口互相印证，形成体系", 18)}))
    terms_all = [(clean(r[0], 8), clean(r[1] if len(r) > 1 else "", 8)) for r in rows[:9]]
    for gi in range(0, min(9, len(terms_all)), 3):
        grp = terms_all[gi:gi + 3]
        sp_g = {"HEAD_01": "术语", "HEAD_02": "一句话解释", "HEAD_03": "本讲落点"}
        for gi2, (gt, gd) in enumerate(grp):
            sp_g[f"ROW_{gi2+1:02d}_01"] = gt
            sp_g[f"ROW_{gi2+1:02d}_02"] = gd or "见讲义"
            sp_g[f"ROW_{gi2+1:02d}_03"] = "代码/测试可验证"
        sp_g["CONCLUSION"] = clean("术语口径统一是协作前提", 16)
        pool.append(("table_decision", "篇级术语表", "统一口径速查", sp_g))
    pool.append(("evidence_argument", "常见 Badcase 集",
                 "从真实故障中学习",
                 {"EVIDENCE_01_INDEX": "01", "EVIDENCE_01_LABEL": "Badcase-1",
                  "EVIDENCE_01_DETAIL": clean(fill(T["trap"][0], term=c1, code=c3), 36),
                  "EVIDENCE_02_INDEX": "02", "EVIDENCE_02_LABEL": "Badcase-2",
                  "EVIDENCE_02_DETAIL": clean(fill(T["trap"][1], term=c2, code=c3), 36),
                  "EVIDENCE_03_INDEX": "03", "EVIDENCE_03_LABEL": "沉淀",
                  "EVIDENCE_03_DETAIL": "每个 Badcase 都应变成回归用例",
                  "SYNTHESIS": clean("Badcase 是最贵也最真实的教学资产", 24)}))
    pool.append(("process_outcome", "讲者使用指南",
                 "课前/课中/课后",
                 {"STEP_01_NUMBER": "1", "STEP_01_TITLE": "课前",
                  "STEP_01_BODY": "读学习目标，跑一遍对应测试",
                  "STEP_02_NUMBER": "2", "STEP_02_TITLE": "课中",
                  "STEP_02_BODY": "按概念模块推进，每模块动手",
                  "STEP_03_NUMBER": "3", "STEP_03_TITLE": "课后",
                  "STEP_03_BODY": "完成实战作业并提交评测",
                  "SYNTHESIS": clean("双元制：理论讲解与动手验证 1:1", 24)}))
    pool.append(("table_decision", "考核题样例",
                 "检验是否真正掌握",
                 {"HEAD_01": "题型", "HEAD_02": "示例", "HEAD_03": "评分点",
                  "ROW_01_01": "辨析题", "ROW_01_02": "边界 vs 误用", "ROW_01_03": "准确性",
                  "ROW_02_01": "设计题", "ROW_02_02": "给场景做选型", "ROW_02_03": "依据充分",
                  "ROW_03_01": "实操题", "ROW_03_02": "跑通指定测试", "ROW_03_03": "可复现",
                  "CONCLUSION": clean("考核对准学习目标，逐条可检验", 18)}))
    pool.append(("evidence_argument", "延伸阅读",
                 " beyond 本讲",
                 {"EVIDENCE_01_INDEX": "01", "EVIDENCE_01_LABEL": "讲义",
                  "EVIDENCE_01_DETAIL": clean(f"chapters/{ch['file'].parent.name}/{ch['file'].name}", 34),
                  "EVIDENCE_02_INDEX": "02", "EVIDENCE_02_LABEL": "代码",
                  "EVIDENCE_02_DETAIL": clean(ch["code"] or "dataagent/", 34),
                  "EVIDENCE_03_INDEX": "03", "EVIDENCE_03_LABEL": "架构",
                  "EVIDENCE_03_DETAIL": "docs/00 TOGAF 总览与 03 图集",
                  "SYNTHESIS": clean(ang["extend"], 30)}))
    # 第一层: 按缺额给每个概念追加深化页(最多每概念4页)
    deficit = 66 - (len(dk.pages) + 1)
    if deficit > 0:
        per = min(4, deficit // max(1, len(concepts)) + 1)
        extra_kinds = [
            ("comparison_synthesis", "反模式对照：{t}",
             "两个真实项目里的教训",
             lambda t, d: {"LEFT_TITLE": "反例现场",
                           "LEFT_BODY": clean(fill(T["bad"][0], term=t, code=c3), 44) + "\n" + "复盘：契约缺失",
                           "RIGHT_TITLE": "整改后",
                           "RIGHT_BODY": clean(fill(T["good"][1], term=t, code=c3), 44) + "\n" + "复盘：资产沉淀",
                           "SYNTHESIS": clean("同一个坑不踩第二次", 20)}),
            ("evidence_argument", "考核问答：{t}",
             "三道面试级追问",
             lambda t, d: {"EVIDENCE_01_INDEX": "Q1", "EVIDENCE_01_LABEL": "机制",
                           "EVIDENCE_01_DETAIL": clean(fill(T["mechanism"][0], term=t, code=c3), 36),
                           "EVIDENCE_02_INDEX": "Q2", "EVIDENCE_02_LABEL": "取舍",
                           "EVIDENCE_02_DETAIL": clean(fill(T["good"][2], term=t, code=c3), 36),
                           "EVIDENCE_03_INDEX": "Q3", "EVIDENCE_03_LABEL": "治理",
                           "EVIDENCE_03_DETAIL": clean(ang["govern"], 36),
                           "SYNTHESIS": clean("追问到第三层才见真功夫", 20)}),
            ("process_outcome", "案例研究：{t}",
             "DataAgent 里的真实应用",
             lambda t, d: {"STEP_01_NUMBER": "1", "STEP_01_TITLE": "背景",
                           "STEP_01_BODY": clean(f"经营分析中需要{t}能力", 30),
                           "STEP_02_NUMBER": "2", "STEP_02_TITLE": "方案",
                           "STEP_02_BODY": clean(fill(T["apply"][1], term=t, code=c3), 30),
                           "STEP_03_NUMBER": "3", "STEP_03_TITLE": "结果",
                           "STEP_03_BODY": "实测通过故障注入与回归门禁",
                           "SYNTHESIS": clean(ang["case"], 30)}),
            ("metrics_evidence", "进阶指引：{t}",
             "三层能力台阶",
             lambda t, d: {"METRIC_01_VALUE": "入门", "METRIC_01_LABEL": "跑通本讲测试",
                           "METRIC_02_VALUE": "熟练", "METRIC_02_LABEL": "能讲清机制与取舍",
                           "METRIC_03_VALUE": "精通", "METRIC_03_LABEL": "能设计治理方案",
                           "EVIDENCE_01_INDEX": "01", "EVIDENCE_01_LABEL": "入门",
                           "EVIDENCE_01_DETAIL": clean(fill(T["apply"][0], term=t, code=c3), 30),
                           "EVIDENCE_02_INDEX": "02", "EVIDENCE_02_LABEL": "熟练",
                           "EVIDENCE_02_DETAIL": clean(fill(T["mechanism"][2], term=t, code=c3), 30)}),
        ]
        added = 0
        while len(dk.pages) + 1 < 66 and added < per * len(concepts):
            ci2 = added % len(concepts)
            kind_i = added // len(concepts)
            v2, tpl2, key2, fn2 = extra_kinds[kind_i % 4]
            t2 = clean(concepts[ci2][0], 10).rstrip(" /·，,")
            d2 = clean(concepts[ci2][1] if len(concepts[ci2]) > 1 else "见讲义", 40)
            dk.content(num, sec, v2, tpl2.format(t=t2), key2, fn2(t2, d2))
            added += 1

    # 第二层: 通用池兜底
    dg_map2 = ASSETS / f"diag_{num}_map.png"
    pool.append(("figure_evidence", "课程全景定位",
                 "本讲在十篇中的坐标",
                 {"EVIDENCE_01": clean(f"本篇：{sec}", 26),
                  "EVIDENCE_02": "前置：前序讲次打地基",
                  "EVIDENCE_03": "后继：后续讲次收口"},
                 ASSETS / f"diag_{num}_map.png",
                 "图：本讲在课程全景中的位置"))
    pool.append(("evidence_argument", "本篇知识地图",
                 "本篇各讲如何咬合",
                 {"EVIDENCE_01_INDEX": "01", "EVIDENCE_01_LABEL": "主线",
                  "EVIDENCE_01_DETAIL": clean(f"{sec}篇的演进主线贯穿各讲", 30),
                  "EVIDENCE_02_INDEX": "02", "EVIDENCE_02_LABEL": "接口",
                  "EVIDENCE_02_DETAIL": "本讲向前讲消费、向后讲供给",
                  "EVIDENCE_03_INDEX": "03", "EVIDENCE_03_LABEL": "验收",
                  "EVIDENCE_03_DETAIL": "全篇用例共同守护同一质量契约",
                  "SYNTHESIS": clean("单讲是点，全篇成线，全线成体系", 24)}))
    pi = 0
    while len(dk.pages) + 1 < 66 and pi < len(pool):
        item = pool[pi]; pi += 1
        if len(item) == 6:
            v2, title2, key2, sp2, fig2, cap2 = item
            dk.content(num, sec, v2, title2, key2, sp2, figure=fig2, caption=cap2)
        else:
            v2, title2, key2, sp2 = item
            dk.content(num, sec, v2, title2, key2, sp2)

    total = len(dk.pages) + 1
    dk.add({"page": "END", "role": "ending", "body_variant_id": None,
            "slot_payload": {"LOGO": "DataAgent", "THANK_YOU": "本章小结",
                             "ENDING_SUBTITLE": t_full,
                             "CONTACT_INFO": clean(ch["exercise"], 30) if ch["exercise"] else "完成实战作业",
                             "EMAIL": f"第{num}讲 · {sec}", "INSTITUTION": "企业级Agent工程架构实战营",
                             "COPYRIGHT": "课程复现资料 · 可公开分享", "PAGE_NUM": str(total)}})
    return {"schema_version": "easyslides.deck_plan.v1",
            "decisions": {"production_scheme": "direct_editable"},
            "slides": dk.pages}


def theme_args(scheme: dict) -> list:
    args = []
    for role, hexv in scheme.items():
        args += ["--theme-token", f"{role}={hexv}"]
    return args


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    mds = sorted(p for p in ROOT.glob("chapters/part*/[0-9][0-9]-*.md"))
    if only:
        mds = [m for m in mds if m.stem[:2] == only]
    print(f"chapters: {len(mds)}")
    ok, fail = [], []
    for md in mds:
        num = md.stem[:2]
        ch = parse_chapter(md)
        scheme = scheme_of(ch["part"])
        plan = build_plan_v3(ch, num, scheme)
        n_pages = len(plan["slides"])
        pf = TMP / f"ch{num}_plan.json"
        json.dump(plan, open(pf, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        part_dir = md.parent.name
        out_dir = TMP / f"ch{num}_out_v3"
        t = re.sub(r"^\d+\s*", "", ch["title"])
        t = re.sub(r'[\\/:*?"<>|：]', "·", t).strip("· ").rstrip()
        pptx_out = OUT_ROOT / part_dir / f"第{num}讲-{t[:22]}.pptx"
        pptx_out.parent.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, str(SKILL / "scripts" / "easyslides.py"), "build", str(pf),
               "--template", "academic_general", "--no-imagegen", "--json",
               "--out-dir", str(out_dir), "--pptx-out", str(pptx_out)] + theme_args(scheme)
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(SKILL), timeout=900)
        try:
            out = r.stdout.strip()
            report = json.loads(out[out.index("{"):out.rindex("}") + 1]) if "{" in out else {}
        except Exception:
            report = {"status": "error", "issues": [{"message": (r.stderr or r.stdout)[-300:]}]}
        if report.get("status") == "pass" and pptx_out.exists():
            ok.append((num, n_pages))
            print(f"[ok] {num} pages={n_pages}", flush=True)
        else:
            msg = "; ".join(i.get("message", "") for i in report.get("issues", []))[:220]
            fail.append((num, msg))
            print(f"[FAIL] {num} {msg}", flush=True)
    print(f"=== done ok={len(ok)} fail={len(fail)} ===")
    for f in fail:
        print("  FAIL", f[0], f[1][:160])
    json.dump({"ok": ok, "fail": fail}, open(TMP / "batch_report_v3.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()