# 31 MCP 与 CapabilityOps：让跨团队能力可接入、可运营、可审计

> 所属篇：第七篇（Agent 工具/技能治理篇） ｜ 对应代码：`dataagent/contracts/tool.py + infra/security`
> 遵循 **SDD / TDD / DDD / TOGAF** 与软件工程国标约定；全部可离线演示。

---

## 一、本章导语

把本地工具和远程 MCP 能力纳入统一治理。本章讲 MCP 正确定位与适用边界、生产级 MCP Server（认证/隔离/限流/审计）、Capability Registry、动态 Tool Set 编译、Credential Broker、全链路红队。

## 二、教学目标

理解 MCP 定位与边界；建设生产级 MCP 治理；用 Capability Registry 管理能力生命周期。

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

| 能力 | 治理 |
|------|------|
| 认证 | 短期凭据 |
| 隔离 | 租户 |
| 限流 | 配额 |
| 审计 | Tool Trace |
| 可见性 | 动态工具集编译 |

## 五、关键代码（可运行，指向 dataagent 模块）

```python
from dataagent.infra.security.guards import CredentialBroker
cb = CredentialBroker(ttl_s=60)
print(cb.issue('readonly'))  # 短期凭据
```

运行方式：

```bash
cd dataagent && PYTHONPATH=src python -m pytest -k security -v
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

将广告查询/预算调整接入独立 MCP Server并由 Host 控制模型可见工具与真实执行权限；做全链路红队测试。

## 八、思考题与实战作业

对照 DSH 插件接口与 MCP 远程协议，说明进程内扩展 vs 跨进程接入的治理责任差异。
