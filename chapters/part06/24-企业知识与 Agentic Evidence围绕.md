# 24 企业知识与 Agentic Evidence：围绕信息缺口构建可核验的证据包

> 所属篇：第六篇（Agent 上下文治理篇） ｜ 对应代码：`dataagent/domain/analytics.py (AnomalySignature)`
> 遵循 **SDD / TDD / DDD / TOGAF** 与软件工程国标约定；全部可离线演示。

---

## 一、本章导语

围绕信息缺口持续查询，把结果组织成能支撑结论的 Evidence Package。本章讲知识可用性治理、按结构解析、Agentic Search、搜索预算、区分假设/证据/结论、Claim-Evidence 关系。

## 二、教学目标

让企业知识真正可用；以 Agentic Search 收敛证据；建立 Claim-Evidence 支撑结论。

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

| 层次 | 说明 |
|------|------|
| 假设 | 未验证推测 |
| 证据 | 数据/规则 |
| 结论 | 有证据支撑的判断 |
| Claim-Evidence | 每条结论可追溯 |

## 五、关键代码（可运行，指向 dataagent 模块）

```python
from dataagent.domain.analytics import RetailDiagnosisService
svc = RetailDiagnosisService()
sig = svc.diagnose_gmv_drop('gmv', [{'conversion_rate':0.3,'aov':120}])
print(sig.caused_by, sig.evidence_keys)
```

运行方式：

```bash
cd dataagent && PYTHONPATH=src python -m pytest -k contracts -v
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

围绕'GMV 下滑'构建 流量—转化—客单价—库存—退款 的假设树与证据链，定位到具体假设并给证据。

## 八、思考题与实战作业

为 DataAgent 的诊断结论补充证据链与 Claim-Evidence 关系，防止未验证推测写入报告。
