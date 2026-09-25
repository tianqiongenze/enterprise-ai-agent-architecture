# 30 Skill Engineering：把一次成功的经营分析固化为领域能力

> 所属篇：第七篇（Agent 工具/技能治理篇） ｜ 对应代码：`dataagent/infra/skills/skill.py`
> 遵循 **SDD / TDD / DDD / TOGAF** 与软件工程国标约定；全部可离线演示。

---

## 一、本章导语

把经营异常诊断沉淀为可复用、可验证、可版本化的 Skill。本章讲 Skill 任务边界、六层结构、Tool/Workflow/SubAgent 组合、渐进式加载、Skill Validator、生命周期治理。

## 二、教学目标

理解 Skill 六层结构；用组合复用能力；渐进式加载控成本；用 Validator 保证'完成了'。

## 三、心智模型图

```mermaid
flowchart LR
  Goal[业务目标] --> Spec[规格 SPEC]
  Spec --> Contract[契约 Contract]
  Contract --> Test[测试 TDD]
  Test --> Loop[受控执行 Loop]
  Loop --> Verify[独立验证 Verify]
  Verify --> Deliver[渐进交付]


## 四、核心概念拆解

| 层 | 作用 |
|----|------|
| 使命 | 边界声明 |
| 原则 | 领域约束 |
| 步骤 | 工序 |
| 标准 | 完成准则 |
| 验证器 | 校验完成 |
| 产物 | 输出模板 |

## 五、关键代码（可运行，指向 dataagent 模块）

```python
from dataagent.infra.skills.skill import SkillRegistry, build_anomaly_skill
reg = SkillRegistry(); build_anomaly_skill(reg)
print(reg.get('anomaly_diagnosis').steps)
```

运行方式：

```bash
cd dataagent && PYTHONPATH=src python -m pytest -k skills -v
```

## 六、架构 / 时序 / 状态机图

```mermaid
flowchart LR
  Goal[业务目标] --> Spec[规格 SPEC]
  Spec --> Contract[契约 Contract]
  Contract --> Test[测试 TDD]
  Test --> Loop[受控执行 Loop]
  Loop --> Verify[独立验证 Verify]
  Verify --> Deliver[渐进交付]


## 七、候选方案 × 取舍矩阵

将'指标确认—假设—证据—验证—原因—报告'固化为经营异常诊断 Skill，用 Validator 校验结论有指标/证据。

## 八、思考题与实战作业

为 DataAgent 增加一个 Skill Validator 规则，防止'假完成'。
