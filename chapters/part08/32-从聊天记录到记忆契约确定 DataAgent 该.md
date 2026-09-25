# 32 从聊天记录到记忆契约：确定 DataAgent 该记什么、不该记什么

> 所属篇：第八篇（Agent Memory 治理篇） ｜ 对应代码：`dataagent/infra/memory/memory.py`
> 遵循 **SDD / TDD / DDD / TOGAF** 与软件工程国标约定；全部可离线演示。

---

## 一、本章导语

Memory 与 Chat History/Context/State 的边界在哪？权威数据与长期记忆边界？本章讲记忆分类、Memory Policy（写什么/要不要确认/存多久/谁能用）、意义与风险判断、企业级记忆不变量。

## 二、教学目标

划定 Memory 系统边界；建立记忆分类与写入策略；识别记忆价值与风险。

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

| 信息 | 是否入 Memory | 理由 |
|------|--------------|------|
| 用户偏好 | 是 | 跨任务复用 |
| 历史任务引用 | 是 | 参考 |
| 指标口径 | 否 | 权威数据源 |
| 实时经营数据 | 否 | 应实时查 |
| 临时结论/推测 | 否 | 不可信 |

## 五、关键代码（可运行，指向 dataagent 模块）

```python
from dataagent.infra.memory.memory import MemoryPolicyEngine
pol = MemoryPolicyEngine()
print(pol.decide('用户偏好：周报柱状图'))
```

运行方式：

```bash
cd dataagent && PYTHONPATH=src python -m pytest -k memory -v
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

从经营分析中区分用户偏好/历史任务引用/流程经验/禁止写入内容，建立企业级记忆不变量。

## 八、思考题与实战作业

列出三个'看似有用但不应写入 Memory'的信息，并给出理由。
