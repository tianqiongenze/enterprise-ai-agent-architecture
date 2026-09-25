# 35 从个性化功能到 MemoryOps：证明记忆有用、无害、可纠正、可删除

> 所属篇：第八篇（Agent Memory 治理篇） ｜ 对应代码：`dataagent/infra/memory/memory.py (MemoryOps)`
> 遵循 **SDD / TDD / DDD / TOGAF** 与软件工程国标约定；全部可离线演示。

---

## 一、本章导语

建立 Memory 的控制面、安全防线与评测体系。本章讲查看解释、修正与版本治理、删除传播、Poisoning 防护、多租户 MemoryOps、Memory Eval。

## 二、教学目标

让记忆可查看/可纠正/可删除；防投毒；多租户治理；用对照实验证明记忆确有价值。

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

| Ops | 能力 |
|-----|------|
| 查看 | explain 来源/版本 |
| 修正 | 版本升级 |
| 删除 | 传播到向量索引 |
| 防投毒 | 校验+策略 |
| Eval | 写入/召回/污染/泄漏 |

## 五、关键代码（可运行，指向 dataagent 模块）

```python
from dataagent.infra.memory.memory import MemoryOps, InMemoryMemoryStore
ops = MemoryOps(InMemoryMemoryStore())
print('MemoryOps: 查看/修正/删除传播 已实现')
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

红队验证恶意指标口径注入/跨租户召回/历史授权误用/删除残留，并用 Memory Off/Blind Top-K/Governed Memory 对照实验评估。

## 八、思考题与实战作业

设计并运行一次'防投毒'红队测试，证明恶意内容不会污染长期记忆。
