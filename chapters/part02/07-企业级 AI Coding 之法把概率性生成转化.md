# 07 企业级 AI Coding 之法：把概率性生成转化为确定性交付

> 所属篇：第二篇（企业级 AI Coding 的道法术器） ｜ 对应代码：`docs/01 + dataagent/tests`
> 遵循 **SDD / TDD / DDD / TOGAF** 与软件工程国标约定；全部可离线演示。

---

## 一、本章导语

为什么复杂工程任务不能只靠'一条好 Prompt'？因为存在目标/上下文/执行/验证四类不确定性。本章给出 SDD、SPEC、Contract-First、Task Graph、TDD、Loop、Verification、Progressive Delivery。

## 二、教学目标

理解四类不确定性；掌握 SDD 把模糊需求变为可执行规格；掌握独立验证与渐进交付。

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

| 不确定性 | 缓解方法 |
|----------|----------|
| 目标 | SDD/SPEC |
| 上下文 | Context Engineering |
| 执行 | Contract-First + Task Graph |
| 验证 | Independent Verification / Eval |

## 五、关键代码（可运行，指向 dataagent 模块）

```python
def analyze(query):
    return '结论已生成，且通过指标与证据校验'
def test_acceptance_drives_spec():
    assert '证据' in analyze('华东 GMV 下滑')  # TDD 先行
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

本仓库即 SDD 样例：先有 docs/01 规格与 tests，再有实现与 CI 门禁。请阅读 dataagent/tests/unit/test_llm_runtime.py，说明它如何印证'Test-Driven 与 Eval-Driven Development'。

## 八、思考题与实战作业

选择一个业务需求，先写失败测试再实现，体验 SDD→TDD 闭环。
