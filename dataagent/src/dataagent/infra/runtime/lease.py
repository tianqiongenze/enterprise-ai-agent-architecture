# -*- coding: utf-8 -*-
"""跨 Worker 租约接管（GAP-14：从"登记未实现"到"最小可用实现"）。

问题：长任务被某个 Worker 领取后该 Worker 崩溃——没有租约机制，任务要么永久卡死
（等人工）要么被其他 Worker 盲目重领（重复执行）。租约 = 有期限的所有权声明。

语义（对齐第 19 课 nack/重投递模型）：
- ``acquire``：首次领取 / 持有者续约 —— 他人持有且未过期 → PermissionError（抢占拒绝）；
- ``renew``：仅持有者可续（他人续约被拒，防串扰）；
- ``release``：显式归还（ack 路径）；
- ``takeover``：**只有租约过期才允许**接管，且接管后 generation+1
  （fencing token——旧 Worker 复活后凭 generation 识别"我已被顶替"）。

边界与诚实登记：
- 这是单进程内存实现（租约状态不跨进程）；生产需把状态放 CRDB/Redis
  （fencing token + TTL key），**协议已稳定，只换存储**（对齐 TaskQueue 端口哲学）；
- 时钟可注入（``clock``），接管时序可确定性测试（无真实等待）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

DEFAULT_LEASE_S = 30.0


@dataclass
class Lease:
    task_id: str
    owner: str
    acquired_at: float
    lease_s: float
    generation: int = 1  # fencing token：每次接管 +1
    renewed_at: float = 0.0
    released_at: Optional[float] = None

    def __post_init__(self):
        if self.renewed_at <= 0:
            self.renewed_at = self.acquired_at

    def expires_at(self) -> float:
        return self.renewed_at + self.lease_s

    def expired(self, now: float) -> bool:
        return self.released_at is None and now > self.expires_at()


class LeaseRegistry:
    """内存租约簿：acquire/renew/release/takeover 四语义，接管仅限过期租约。"""

    def __init__(self, *, default_lease_s: float = DEFAULT_LEASE_S,
                 clock: Callable[[], float] = time.time):
        self.default_lease_s = default_lease_s
        self._clock = clock
        self._leases: dict[str, Lease] = {}

    # ---- 领取 / 续约 ----

    def acquire(self, task_id: str, owner: str,
                *, lease_s: Optional[float] = None) -> Lease:
        now = self._clock()
        cur = self._leases.get(task_id)
        if cur is not None and cur.released_at is None and not cur.expired(now):
            if cur.owner != owner:
                raise PermissionError(
                    f"任务 {task_id} 已被 {cur.owner} 领取(至 {cur.expires_at():.3f})，拒绝抢占"
                )
            cur.renewed_at = now  # 持有者重复 acquire = 续约
            return cur
        if (cur is not None and cur.owner == owner and cur.released_at is None
                and cur.expired(now)):
            # 过期后被自己领回：所有权延续，generation 不变（未发生接管）
            cur.acquired_at = cur.renewed_at = now
            return cur
        lease = Lease(task_id=task_id, owner=owner, acquired_at=now,
                      lease_s=lease_s if lease_s is not None else self.default_lease_s,
                      renewed_at=now)
        self._leases[task_id] = lease
        return lease

    def renew(self, task_id: str, owner: str) -> bool:
        """心跳续约：仅当前持有者可续（他人/不存在 → False）。"""
        cur = self._leases.get(task_id)
        if cur is None or cur.owner != owner or cur.released_at is not None:
            return False
        if cur.expired(self._clock()):
            return False  # 已过期：续约无效，走 takeover
        cur.renewed_at = self._clock()
        return True

    def release(self, task_id: str, owner: str) -> bool:
        """显式归还（ack 路径）。非持有者归还 → False（防串扰）。"""
        cur = self._leases.get(task_id)
        if cur is None or cur.owner != owner or cur.released_at is not None:
            return False
        cur.released_at = self._clock()
        return True

    # ---- 接管 ----

    def takeover(self, task_id: str, new_owner: str) -> bool:
        """接管过期租约：generation+1（fencing）。未过期 → PermissionError。"""
        now = self._clock()
        cur = self._leases.get(task_id)
        if cur is None:
            return False
        if cur.released_at is not None:
            return False  # 已归还：正常流转用 acquire，不走接管
        if not cur.expired(now):
            raise PermissionError(
                f"任务 {task_id} 租约未过期(持有者 {cur.owner})，禁止接管"
            )
        if cur.owner == new_owner:
            return False  # 自己接管自己无意义（续约即可）
        cur.owner = new_owner
        cur.generation += 1
        cur.acquired_at = cur.renewed_at = now
        cur.released_at = None
        return True

    # ---- 查询 ----

    def current(self, task_id: str) -> Optional[Lease]:
        return self._leases.get(task_id)

    def generation_of(self, task_id: str) -> int:
        """fencing token 查询：无租约 → 0。"""
        cur = self._leases.get(task_id)
        return cur.generation if cur else 0

    def is_current(self, task_id: str, owner: str) -> bool:
        """Worker 执行前自校验：我还是当前持有者吗（fencing 检查点）。"""
        cur = self._leases.get(task_id)
        return bool(cur and cur.released_at is None and cur.owner == owner
                    and not cur.expired(self._clock()))

    def expired_leases(self) -> list[Lease]:
        now = self._clock()
        return [c for c in self._leases.values()
                if c.released_at is None and c.expired(now)]
