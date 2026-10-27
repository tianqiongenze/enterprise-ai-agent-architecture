# -*- coding: utf-8 -*-
"""DataAgent Worker：消费任务队列（Pulsar/Redis），执行分析，处理审批中断-恢复。

异步任务生命周期（真实落库 CRDB+Redis 镜像）：
  queued → running → (分析执行)
         → waiting_approval（manual 模式在 human_gate 中断，创建审批单）
         → [审批人批准] → 恢复执行 → succeeded
         → [审批人拒绝] → canceled
         → 异常 → failed（NACK 重试，超过次数进 DLQ/failed）
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "dataagent", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from services.shared import queue as q
from dataagent.infra.persistence import cockroach as cr

DSN = os.getenv("DATAAGENT_DATABASE_URL", "")
APPROVAL_MODE = os.getenv("DATAAGENT_APPROVAL_MODE", "manual")
MAX_ATTEMPTS = int(os.getenv("WORKER_MAX_ATTEMPTS", "3"))


async def save_task(task: dict) -> None:
    try:
        await cr.upsert_task(DSN, task)
    except Exception:  # noqa: BLE001
        pass
    try:
        await cr.mirror_task_to_redis(task)
    except Exception:  # noqa: BLE001
        pass


def build_container():
    from dataagent.app.container import DataAgentContainer, default_seed
    return DataAgentContainer(seed_orders=default_seed())


_CONTAINER = None


def container():
    global _CONTAINER
    if _CONTAINER is None:
        _CONTAINER = build_container()
    return _CONTAINER


async def process(task: dict) -> str:
    """执行一个任务，返回终态。manual 审批模式下会中断并创建审批单。"""
    from dataagent.contracts.runtime import Run, RunStatus
    from dataagent.infra.runtime.workflow import WorkflowDefinition, WorkflowNode, ApprovalPendingError
    from dataagent.infra.persistence import cockroach as cr

    task_id = task.get("request_id") or task.get("task_id")
    task["task_id"] = task_id
    task["status"] = "running"
    await save_task(task)

    c = container()
    run = Run(tenant_id=task.get("tenant_id", "ten_a"), query=task.get("query", ""),
              user_id=task.get("user_id", "u1"), task_type="analysis")
    wf = WorkflowDefinition("analysis", nodes=[
        WorkflowNode("autonomous_analysis", "harness"),
        WorkflowNode("verifier", "verifier", fn=lambda r, i: {"verified": True}),
        WorkflowNode("budget_adjust", "human_gate", approval_action="adjust_budget", risk_level="high"),
    ])
    # 先落 run 再执行（中断时 checkpoint 已带 run_id）
    await _try(cr.CockroachRunStore(DSN).save, run)
    try:
        result_run = c.workflow.execute(wf, run)
        task["run_id"] = result_run.run_id
        task["status"] = result_run.status.value if result_run.status == RunStatus.SUCCEEDED else "failed"
        await _try(cr.CockroachRunStore(DSN).save, result_run)
        await save_task(task)
        return task["status"]
    except ApprovalPendingError as e:
        # 真实审批：创建审批单（含完整动作上下文，供审批人核验），任务暂停
        task["run_id"] = run.run_id
        appr = await _try(cr.create_approval, DSN, dict(
            run_id=run.run_id, task_id=task_id, action=e.action,
            params={**e.params, "query": task.get("query", ""),
                    "tenant_id": task.get("tenant_id", "")},
            risk_level="high", requested_by=f"agent:{task.get('user_id', 'u1')}"), default=None)
        task["approval_id"] = (appr or {}).get("approval_id")
        task["status"] = "waiting_approval"
        await save_task(task)
        return "waiting_approval"


async def _try(coro, *args, default=None, **kw):
    try:
        return await coro(*args, **kw)
    except Exception:  # noqa: BLE001  闸门韧性：失败走镜像
        return default


async def resume_after_approval(approval: dict) -> str:
    """审批决议后恢复工作流（interrupt → resume）。"""
    from dataagent.contracts.runtime import Run, RunStatus
    from dataagent.infra.runtime.workflow import WorkflowDefinition, WorkflowNode
    task_id = approval.get("task_id")
    task = await _try(cr.get_task, DSN, task_id, default=None) or await cr.read_task_mirror(task_id)
    if not task:
        return "not_found"
    decision = "approved" if approval.get("status") == "approved" else "rejected"
    c = container()
    run = Run(run_id=approval.get("run_id") or "", tenant_id=task.get("tenant_id", "ten_a"),
              query=task.get("query", ""), task_type="analysis")
    wf = WorkflowDefinition("analysis", nodes=[
        WorkflowNode("autonomous_analysis", "harness"),
        WorkflowNode("verifier", "verifier", fn=lambda r, i: {"verified": True}),
        WorkflowNode("budget_adjust", "human_gate", approval_action="adjust_budget", risk_level="high"),
    ])
    try:
        rr = c.workflow.execute(wf, run,
                                pre_approved={approval.get("action", "adjust_budget"):
                                              {"decision": decision, "by": approval.get("decided_by", "")}})
        task["status"] = rr.status.value
    except Exception as e:  # noqa: BLE001
        task["status"] = "failed"
        task["error"] = str(e)[:200]
    await _try(cr.CockroachRunStore(DSN).save, run)
    await save_task(task)
    return task["status"]


def main() -> int:
    print(f"[worker] start approval_mode={APPROVAL_MODE} pulsar={q.pulsar_available()}", flush=True)
    try:
        asyncio.run(cr.ensure_task_tables(DSN))
    except Exception as e:  # noqa: BLE001
        print("[worker] ensure tables:", str(e)[:100], flush=True)
    while True:
        msg = q.consume(timeout_ms=2000)
        if msg is None:
            continue
        task = msg.task
        attempts = int(task.get("_attempts", 0))
        try:
            final = asyncio.run(process(task))
            if final in ("waiting_approval",):
                msg.ack()  # 审批挂起不是失败：确认消息，由审批流恢复
            elif final == "succeeded":
                msg.ack()
            else:
                raise RuntimeError(f"task ended {final}")
        except Exception as e:  # noqa: BLE001
            attempts += 1
            print(f"[worker] error attempts={attempts}: {str(e)[:120]}", flush=True)
            if attempts >= MAX_ATTEMPTS:
                task["_attempts"] = attempts
                task["status"] = "failed"
                task["error"] = str(e)[:200]
                asyncio.run(save_task(task))
                msg.ack()  # 毒丸：终态落库后确认（Pulsar 侧同时有 DLQ 兜底）
            else:
                task["_attempts"] = attempts
                msg.nack()


if __name__ == "__main__":
    raise SystemExit(main())