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
from dataagent.infra.runtime.lease import LeaseRegistry

DSN = os.getenv("DATAAGENT_DATABASE_URL", "")
APPROVAL_MODE = os.getenv("DATAAGENT_APPROVAL_MODE", "manual")
MAX_ATTEMPTS = int(os.getenv("WORKER_MAX_ATTEMPTS", "3"))

# GAP-14 生产接线（ADR-018）：领取任务前先拿租约——
# ack 成功 → release（正常流转）；nack → 不 release，租约自然过期供其他 Worker 接管。
# 内存租约簿仅本进程有效；生产把 LeaseRegistry 换成 Redis/CRDB 后端（协议不变）。
# GAP-33：WORKER_ID 必须跨 pod 唯一——容器内 pid 恒为 1，{hostname}-{pid}
# 才能区分双 Worker（真机取证：双 pod 同名 worker-1 导致跨 pod 租约冲突）。
import socket as _socket

WORKER_ID = os.getenv("WORKER_ID") or f"worker-{_socket.gethostname()}-{os.getpid()}"
_LEASES = LeaseRegistry(default_lease_s=float(os.getenv("WORKER_LEASE_S", "300")))


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


def run_once(timeout_ms: int = 2000) -> Optional[str]:
    """消费并处理一条任务（GAP-14 探针/测试入口）。无任务返回 None，有任务返回终态。"""
    msg = q.consume(timeout_ms=timeout_ms)
    if msg is None:
        return None
    task = msg.task
    task_id = task.get("request_id") or task.get("task_id") or f"anon-{time.time()}"
    try:
        _LEASES.acquire(task_id, WORKER_ID)
    except PermissionError as e:
        print(f"[worker] 租约冲突 {task_id}: {str(e)[:100]}", flush=True)
        msg.nack()
        return "lease_conflict"
    try:
        final = asyncio.run(process(task))
        if final in ("succeeded", "waiting_approval"):
            msg.ack()
            _LEASES.release(task_id, WORKER_ID)  # 正常流转（ADR-018）
            return final
        raise RuntimeError(f"task ended {final}")
    except Exception as e:  # noqa: BLE001
        # nack 且不 release：租约自然过期 → 其他 Worker 可接管（ADR-018）
        msg.nack()
        print(f"[worker] run_once 失败 {task_id}: {str(e)[:120]}", flush=True)
        raise


def main() -> int:
    once = "--once" in sys.argv
    print(f"[worker] start id={WORKER_ID} approval_mode={APPROVAL_MODE} "
          f"pulsar={q.pulsar_available()} backend={q._backend() or 'auto'} "
          f"once={once} lease_s={_LEASES.default_lease_s}", flush=True)
    try:
        asyncio.run(cr.ensure_task_tables(DSN))
    except Exception as e:
        print("[worker] ensure tables:", str(e)[:100], flush=True)
    while True:
        msg = q.consume(timeout_ms=2000)
        if msg is None:
            if once:
                print("[worker] --once: 队列空，退出", flush=True)
                return 0
            continue
        task = msg.task
        attempts = int(task.get("_attempts", 0))
        task_id = task.get("request_id") or task.get("task_id") or f"anon-{time.time()}"
        try:
            _LEASES.acquire(task_id, WORKER_ID)
        except PermissionError as e:
            print(f"[worker] 租约冲突（他人持有，稍后重投）{task_id}: {str(e)[:100]}", flush=True)
            msg.nack()
            if once:
                return 1
            continue
        try:
            final = asyncio.run(process(task))
            if final in ("waiting_approval",):
                msg.ack()  # 审批挂起不是失败：确认消息，由审批流恢复
                _LEASES.release(task_id, WORKER_ID)
            elif final == "succeeded":
                msg.ack()
                _LEASES.release(task_id, WORKER_ID)
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
                _LEASES.release(task_id, WORKER_ID)
            else:
                task["_attempts"] = attempts
                msg.nack()  # 不 release：租约自然过期 → 其他 Worker 可接管（ADR-018）
        if once:
            print(f"[worker] --once: 处理完成 {task_id} → {task.get('status')}", flush=True)
            return 0


if __name__ == "__main__":
    raise SystemExit(main())