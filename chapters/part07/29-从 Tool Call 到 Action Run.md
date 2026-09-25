# 29 从 Tool Call 到 Action Runtime：把高风险行动收进受控执行闭环

> 所属篇：第七篇（Agent 工具/技能治理篇） ｜ 对应代码：`dataagent/contracts/runtime.py + infra/runtime/workflow.py`
> 遵循 **SDD / TDD / DDD / TOGAF** 与软件工程国标约定；全部可离线演示。

---

## 一、本章导语

防止模型直接操作真实业务。本章讲 Tool Call 与真实执行解耦、Action 生命周期（提议-校验-授权-审批-执行-验真）、风险分级、最小权限/短期凭据、幂等与状态一致。

## 二、教学目标

把副作用收进受控闭环；实现风险分级与控制权；最小权限与幂等保护。

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

| 阶段 | 动作 |
|------|------|
| 提议 | 模型生成参数 |
| 校验 | Schema/权限 |
| 授权 | 风险分级 |
| 审批 | 人工或策略 |
| 执行 | 幂等执行 |
| 验真 | 结果验证 |

## 五、关键代码（可运行，指向 dataagent 模块）

```python
from dataagent.infra.runtime.workflow import IdempotencyStore
idem = IdempotencyStore()
print(idem.try_mark('budget:2026-09-25:CN'))  # 幂等键保护
```

运行方式：

```bash
cd dataagent && PYTHONPATH=src python -m pytest -k integration -v
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

完成 DataAgent 预算调整实战：预览→审批→受控执行→结果验证闭环，用 Action Badcase（重复/篡改/假成功/部分执行）验证安全边界。

## 八、思考题与实战作业

列出 DataAgent 中所有有副作用工具，按风险分级并设最小权限。
