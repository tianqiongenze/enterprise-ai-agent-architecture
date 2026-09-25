# 05 从根本讲透 LLM 调优技术：PE、CE、HE、LE、GE

> 所属篇：第一篇（AI 核心认知篇） ｜ 对应代码：`dataagent/infra/context/assembler.py + harness.py`
> 遵循 **SDD / TDD / DDD / TOGAF** 与软件工程国标约定；全部可离线演示。

---

## 一、本章导语

PE(Prompt)/CE(Context)/HE(Harness)/LE(Loop)/GE(Graph) 五层技术的关系是递进、嵌套还是取代？本章从 OpenAI 五级路线图出发讲清归属。

## 二、教学目标

理解五层技术关系与适用；从 User 与 Builder 双重视角看五层；知道何时该用 Prompt/Context/Harness/Loop 或保持简单。

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

| 层 | 作用 | User 视角 | Builder 视角 |
|----|------|----------|-------------|
| PE | 表达目标 | 写好 Prompt | 输出契约 |
| CE | 准备信息 | 构建上下文 | Context Runtime |
| HE | 调用工具 | 声明工具 | 权限策略 |
| LE | 迭代验证 | 逐步逼近 | 评测/反馈 |
| GE | 编排复杂 | 定义图 | 多 Agent 编排 |

## 五、关键代码（可运行，指向 dataagent 模块）

```python
from dataagent.infra.context.assembler import ContextAssembler, ContextContract
ass = ContextAssembler()
# CE: 面向'规划'决策步骤装配最小充分上下文
sl = ass.assemble(step_contract=ContextContract('planning', required=('metric_registry',)))
print('充分性检查缺失项:', sl.filtered[-1:] )
```

运行方式：

```bash
cd dataagent && PYTHONPATH=src python -m pytest -k context -v
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

模型内化趋势越强，越应把稳定工程对象（输出契约/校验/评测）做在系统层而非 Prompt 里。试以 DataAgent 的'指标口径'说明为什么不能只靠 Prompt。

## 八、思考题与实战作业

以'指标口径'为例说明：为什么不能只把口径写进 Prompt，而要建 Metric Registry 并经 Context 硬过滤注入？
