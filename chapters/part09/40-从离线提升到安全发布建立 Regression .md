# 40 从离线提升到安全发布：建立 Regression Gate 与受控进化闭环

> 所属篇：第九篇（Agent 评测与受控进化篇） ｜ 对应代码：`dataagent/infra/metrics + .github/workflows/ci.yml`
> 遵循 **SDD / TDD / DDD / TOGAF** 与软件工程国标约定；全部可离线演示。

---

## 一、本章导语

建立从候选评测到灰度发布、回滚、反馈回流的受控进化。本章讲 Agent 资产统一版本、Baseline/Candidate 公平比较、CI Regression Gate、Shadow/Canary、Kill Switch、AI 自动优化的责任边界。

## 二、教学目标

统一版本治理；公平比较；用回归门禁拦截关键退化；Shadow/Canary 与回滚。

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

| 机制 | 作用 |
|------|------|
| 版本元组 | 公平比较 |
| CI Gate | 拦截退化 |
| Canary | 灰度验证 |
| Kill Switch | 快速止血 |
| 回滚 | 恢复完整 Agent |

## 五、关键代码（可运行，指向 dataagent 模块）

```python
# GitHub Actions 已内置回归门禁
# .github/workflows/ci.yml → pytest + 端到端
print('候选评测→门禁阻断→修复验证→灰度→回滚 全流程')
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

完成 DataAgent 发布实战：候选评测、门禁阻断、修复验证、租户灰度、异常回滚全流程（对齐 ci.yml）。

## 八、思考题与实战作业

模拟一次候选版本触发回归门禁阻断，修复后重新通过，体验受控进化闭环。
