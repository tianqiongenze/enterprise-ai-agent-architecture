# 34 从向量 Top-K 到 Recall Contract：让记忆在正确 Step 进入 Context

> 所属篇：第八篇（Agent Memory 治理篇） ｜ 对应代码：`dataagent/infra/memory/memory.py (MemoryRecall)`
> 遵循 **SDD / TDD / DDD / TOGAF** 与软件工程国标约定；全部可离线演示。

---

## 一、本章导语

不是所有步骤都用同一套检索。本章讲 Recall Contract、租户/用户/权限过滤、时效状态过滤、企业级召回排序、召回/注入/行动权限分离、Context Budget 与最小注入、使用追踪。

## 二、教学目标

建立面向步骤的受控召回；过滤租户权限与时效；排序综合相关性/范围/可信度/新鲜度。

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

| 过滤 | 说明 |
|------|------|
| 租户/用户 | 防止泄漏 |
| 时效/状态 | 过期失效 |
| 角色 | 最小注入 |
| 排序 | 多因子 |

## 五、关键代码（可运行，指向 dataagent 模块）

```python
from dataagent.infra.memory.memory import MemoryRecall, InMemoryMemoryStore
rc = MemoryRecall(InMemoryMemoryStore())
print(rc.recall('偏好', tenant_id='t', owner='u'))
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

规划阶段引用历史行动、报告阶段用表达偏好，但重新查询当前经营数据与权限（对齐 tests）。

## 八、思考题与实战作业

实现一次跨租户召回攻击并验证被 Recall Contract 拦截。
