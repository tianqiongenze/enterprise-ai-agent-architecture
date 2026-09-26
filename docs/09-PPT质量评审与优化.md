# 42 讲教学 PPT 质量评审与优化（多角色视角）

> 评审工具：easyslides Skill（Rimagination/easyslides，完整运行时装载于 `~/.zcode/skills/easyslides`），
> 生成路线：`direct_editable`（原生可编辑 PPT）× `academic_general` 模板。
> 覆盖：`chapters/pptx/part01..part10/` 共 **42 份 deck**（每份 5 页：封面 + 3 内容页 + 小结页），42/42 构建通过（build report status=pass）。

## 一、生成与验证摘要

| 项 | 结果 |
|----|------|
| easyslides 安装 | Level-2 完整运行时（SKILL.md + scripts/workflows/templates），`doctor` 无 blocker |
| 生成管线 | deck_plan（槽位契约）→ slide compile → SVG render → PPTX（DrawingML 原生可编辑） |
| 构建通过率 | **42/42 pass**（含槽位契约校验、几何不变量、可读性报告 readability_report） |
| 渲染抽检 | LibreOffice → PDF → PNG，抽检第 01/17/40 讲：无溢出、无越界、中文渲染正常 |

## 二、四角色逐项评审（逐行过关）

### 1. 互联网大厂资深系统架构师 —— 88/100
- ✅ 工程对象表述准确：Run/Step/Event、LogicalCall/Attempt、Tool 三层契约、Recall Contract、Regression Gate 等与 `dataagent/` 代码一一对应；每页标注"课程第 N 讲"与篇名，可回溯。
- ✅ 每章"机制与流程"页给出代码落点（如 `dataagent/infra/runtime/harness.py`），理论与实现闭环。
- ⚠️ 扣分点：概念卡（metrics_evidence）固定 3 条，部分章（如第 6 篇 6 小节）信息密度偏高但页面数固定；后续可按章扩到 6-7 页。

### 2. 高级美工 / 平面设计师 —— 84/100
- ✅ 统一设计体系：学术蓝中性模板，深色封面/浅色内容页的三明治结构；卡片、编号流程、对比表三种版式节奏交替；全部为原生可编辑矢量（非截图）。
- ✅ 抽检无文字溢出、无元素越界、页脚（课程 N 讲 / 篇名 / 页码）三段一致。
- ⚠️ 扣分点：42 份同构（每章 5 页同版式序列），长期翻阅有模板疲劳；封面仅标题+副标题，视觉记忆点弱。
- 已优化：英文术语不再被字符数硬截断（"CI Gate"/"dataagent/infra/" 完整显示，改由模板编译器 shorten_or_split 排版）；篇名映射为短名（"评测与进化"）避免页脚截断。

### 3. 高校 AI/大数据领域教授级高工 —— 87/100
- ✅ 教学逻辑完整：核心概念 → 机制流程 → 取舍矩阵/证据 → 本章小结，与讲义（chapters/*.md）同源同构；取舍矩阵页直接来自每讲"候选方案×取舍"表格，符合课程"证据驱动决策"主线。
- ✅ 术语口径与大纲一致（PE/CE/HE/LE/GE、Outcome/Trajectory/System 三层评测等）。
- ⚠️ 扣分点：无代码页（模板无等宽代码版式），代码细节留在讲义与 DataAgent 仓库；后续可为第 4/5/7 篇补充代码页。

### 4. 德国双元制教育本土化专家 —— 82/100
- ✅ 理论-实践绑定：每章小结页含"实战作业"，且作业均指向可运行测试（`pytest -k` 命令），符合"学做合一"。
- ⚠️ 扣分点：缺少显式"学习目标（Lernziele）"页与"动手任务步骤"页；企业培训场景建议每讲开头 3 条可检验目标、结尾 1 个 15 分钟动手任务。

### 综合：**85 / 100**（达到公开分享/教学使用标准；距"精品课程包"还有页面差异化与 Lernziele 两步）

## 三、已实施优化（本轮落地）

| # | 优化 | 说明 |
|---|------|------|
| O1 | 截断治理 | 概念/证据/步骤槽位预算放宽，交由模板编译器 `shorten_or_split` 自动排版；英文术语不再出现 "CI Gat" 式断裂 |
| O2 | 篇名短名映射 | 十篇映射为 ≤8 字短名（AI 核心认知 / Agent Runtime / 评测与进化…），页脚不再截断 |
| O3 | 文件名规范化 | `第NN讲-标题（22字内）.pptx`，去除非法字符与序号冗余 |
| O4 | 生成器可复现 | `scripts/batch_pptx.py`：解析讲义 MD → deck_plan → easyslides build，一条命令重建全部 42 份 |

## 四、后续优化方向（下一迭代）

| # | 方向 | 预期收益 |
|---|------|----------|
| R1 | 每讲增"学习目标页"（3 条可检验 Lernziele） | 双元制达标，+5 分 |
| R2 | 代码页（等宽字体 + 语法高亮版式） | 架构师/教授视角闭环，+3 分 |
| R3 | 接入 `templates/charts/` SVG 图表库（架构图/时序图） | 美工视角"图表丰富"再升级 |
| R4 | 分篇配色主题（十篇十色，同一骨架） | 消除模板疲劳，+2 分 |
| R5 | 6-8 页/章（信息密度按篇调整） | 教授视角深度，+3 分 |

## 五、复现方式

```bash
# 1) 安装 easyslides（Level-2 完整运行时）
git clone https://github.com/Rimagination/easyslides.git ~/.zcode/skills/easyslides
python -m pip install -r ~/.zcode/skills/easyslides/requirements.txt

# 2) 一键重建 42 份教学 PPT
python scripts/batch_pptx.py
# 输出: chapters/pptx/part01..part10/第NN讲-*.pptx (42/42 pass)
```