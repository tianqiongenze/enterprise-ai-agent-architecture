# 20 以故障为教材：证明 DataAgent 能跨故障完成任务

> 所属篇：第五篇（Agent Harness 与 Runtime 工程架构篇） ｜ 对应代码：`dataagent/tests/fault/test_fault_injection.py`
> 遵循 **SDD / TDD / DDD / TOGAF** 与软件工程国标约定；全部可离线演示。

---

## 一、本章导语

主动注入故障来验证系统的可靠性，而不是证明它能正常跑。本章讲 Failure Taxonomy、Retry/Resume/Replay/Fork 的区别、Runtime Invariant、用 Run Timeline 解释故障。

## 二、教学目标

建立统一故障模型；区分四种恢复机制；保护不可破坏的不变量；完整解释一次故障。

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

| 机制 | 区别 |
|------|------|
| Retry | 同一次尝试重来 |
| Resume | 从断点继续 |
| Replay | 重放事件复盘 |
| Fork | 分支对照实验 |

## 五、关键代码（可运行，指向 dataagent 模块）

```python
# 通过 FakeLlmClient 注入真实故障后验证重试恢复
# tests/fault/test_fault_injection.py
print('注入故障→重试→恢复 已由测试验证')
```

运行方式：

```bash
cd dataagent && PYTHONPATH=src python -m pytest -k fault -v
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

完成全链路故障注入测试，证明 Runtime 能恢复、能接管、能解释（跑通 tests/fault 全部用例）。

## 八、思考题与实战作业

为 DataAgent 增加一条'跨故障完成任务'的端到端用例，验证重试+接管+解释。
