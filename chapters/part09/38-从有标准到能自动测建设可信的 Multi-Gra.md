# 38 从'有标准'到'能自动测'：建设可信的 Multi-Grader 与 Batch Eval Runner

> 所属篇：第九篇（Agent 评测与受控进化篇） ｜ 对应代码：`dataagent/infra/metrics/eval_ops.py (BatchEvalRunner/Grader)`
> 遵循 **SDD / TDD / DDD / TOGAF** 与软件工程国标约定；全部可离线演示。

---

## 一、本章导语

把质量标准转化为批量运行、自动评分、持续回归的评测系统。本章讲按判断对象选 Grader、Code/Environment/Trace/LLM Grader、Grader 校准与版本、Multi-Trial、多维 Scorecard。

## 二、教学目标

按对象选 Grader；区分'说做了'与'真完成'；多 Trial 与稳定性；多维评分卡。

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

| Grader | 判断 |
|--------|------|
| Code | 环境真实结果 |
| Environment | 状态断言 |
| Trace | 执行轨迹 |
| LLM | 开放质量 |

## 五、关键代码（可运行，指向 dataagent 模块）

```python
from dataagent.infra.metrics.eval_ops import BatchEvalRunner, code_grader
runner = BatchEvalRunner([code_grader(lambda r: r.status.value=='succeeded')])
print('批量评分卡由 Grader 组合产生')
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

建设 DataAgent 的 Batch Eval Runner，自动验证指标计算/证据有效性/执行轨迹/环境状态（对齐 tests/integration）。

## 八、思考题与实战作业

为 DataAgent 增加一个 Trace Grader，校验执行路径满足某跳转约束。
