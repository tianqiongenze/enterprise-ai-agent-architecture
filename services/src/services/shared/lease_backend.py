# -*- coding: utf-8 -*-
"""Redis 租约后端（ADR-018 生产形态：协议不变，只换存储）。

与内存 LeaseRegistry 同一四语义（acquire/renew/release/takeover）+ fencing generation。
关键操作用 **Lua 脚本保证原子性**（GET-判断-写回 的竞态窗口在 Redis 侧闭合）：

    acquire : key 存在且未过期且 owner 不同 → 拒绝；owner 相同 → 续约；
              不存在/已过期 → gen=INCR(genkey) 后写入（新领取/接管共用 generation 自增）
    renew   : 仅持有者可续（比对 owner）
    release : 仅持有者可删
    takeover: 仅当 key 不存在（TTL 已过）→ gen 自增写入（世代 +1，fencing）

generation 用独立计数键持久（TTL 过期不丢世代——僵尸 Worker 复活凭世代号自知被顶替）。
测试用 FakeRedis（eval 按 `-- op:` 标记分发到等价 Python 实现）；真实 Redis 由环境门控 e2e 验证。
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable, Optional

ACQUIRE_LUA = """-- op:acquire
local cur = redis.call('GET', KEYS[1])
if cur then
  local st = cjson.decode(cur)
  if st.owner == ARGV[1] then
    st.renewed_at = tonumber(ARGV[2])
    redis.call('SET', KEYS[1], cjson.encode(st), 'PX', tonumber(ARGV[3]))
    return cjson.encode(st)
  end
  return false
end
local gen = redis.call('INCR', KEYS[2])
local st = {owner = ARGV[1], generation = gen, renewed_at = tonumber(ARGV[2])}
redis.call('SET', KEYS[1], cjson.encode(st), 'PX', tonumber(ARGV[3]))
return cjson.encode(st)
"""

RENEW_LUA = """-- op:renew
local cur = redis.call('GET', KEYS[1])
if not cur then return false end
local st = cjson.decode(cur)
if st.owner ~= ARGV[1] then return false end
st.renewed_at = tonumber(ARGV[2])
redis.call('SET', KEYS[1], cjson.encode(st), 'PX', tonumber(ARGV[3]))
return true
"""

RELEASE_LUA = """-- op:release
local cur = redis.call('GET', KEYS[1])
if not cur then return false end
local st = cjson.decode(cur)
if st.owner ~= ARGV[1] then return false end
redis.call('DEL', KEYS[1])
return true
"""

TAKEOVER_LUA = """-- op:takeover
local cur = redis.call('GET', KEYS[1])
if cur then return false end  -- TTL 未过（仍被持有）→ 不可接管
local gen = redis.call('INCR', KEYS[2])
local st = {owner = ARGV[1], generation = gen, renewed_at = tonumber(ARGV[2])}
redis.call('SET', KEYS[1], cjson.encode(st), 'PX', tonumber(ARGV[3]))
return cjson.encode(st)
"""

OPS = {"acquire": ACQUIRE_LUA, "renew": RENEW_LUA, "release": RELEASE_LUA,
       "takeover": TAKEOVER_LUA}


class RedisLeaseRegistry:
    """Redis 租约簿：与内存 LeaseRegistry 同协议（acquire/renew/release/takeover/generation_of）。"""

    def __init__(self, client: Any, *, default_lease_s: float = 300.0,
                 namespace: str = "dataagent:lease",
                 clock: Optional[Callable[[], float]] = None):
        self.client = client
        self.default_lease_s = default_lease_s
        self.ns = namespace
        self._clock = clock or time.time

    def _keys(self, task_id: str) -> tuple[str, str]:
        return (f"{self.ns}:{task_id}", f"{self.ns}gen:{task_id}")

    def _run(self, op: str, task_id: str, owner: str, lease_s: float):
        k, gk = self._keys(task_id)
        now_ms = int(self._clock() * 1000)
        ttl_ms = int(lease_s * 1000)
        res = self.client.eval(OPS[op], 2, k, gk, owner, now_ms, ttl_ms)
        # Lua `return false` 在 RESP 里是 nil bulk → redis-py 解码为 None（真实行为，
        # 由真机联调取证发现：decode_responses=True 时不是 b"false"）——None 语义 = 失败
        if res is None:
            return False
        if isinstance(res, bytes):  # 关闭 decode_responses 的客户端返回 bytes
            res = res.decode("utf-8")
        return json.loads(res) if isinstance(res, str) else res

    def acquire(self, task_id: str, owner: str, *, lease_s: Optional[float] = None) -> dict:
        st = self._run("acquire", task_id, owner, lease_s or self.default_lease_s)
        if st is False:
            raise PermissionError(f"任务 {task_id} 已被他人持有，拒绝抢占")
        return st

    def renew(self, task_id: str, owner: str) -> bool:
        return bool(self._run("renew", task_id, owner, self.default_lease_s))

    def release(self, task_id: str, owner: str) -> bool:
        return bool(self._run("release", task_id, owner, self.default_lease_s))

    def takeover(self, task_id: str, new_owner: str, *, lease_s: Optional[float] = None) -> bool:
        st = self._run("takeover", task_id, new_owner, lease_s or self.default_lease_s)
        if st is False:
            raise PermissionError(f"任务 {task_id} 租约未过期，禁止接管")
        return True

    def generation_of(self, task_id: str) -> int:
        k, gk = self._keys(task_id)
        cur = self.client.get(k)
        if cur:
            return int(json.loads(cur)["generation"])
        return int(self.client.get(gk) or 0)
