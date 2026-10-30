# -*- coding: utf-8 -*-
"""任务队列：Pulsar 主通道（Shared 订阅 + NACK + DLQ）+ Redis List 兜底通道。

调研定案（Pulsar 官方/Spring 文档最佳实践）：
- Shared 订阅实现工作队列语义；consumer 配 DeadLetterPolicy(max_redeliver_count, dead_letter_topic)
- 瞬时失败 negative_acknowledge()（带 redelivery delay），真正完成后才 ack —— 任务幂等设计
- DLQ 作为毒丸逃生舱，单独可查可重放
实现：pulsar-client 可导入且 DATAAGENT_USE_PULSAR=true 时走真实 Pulsar；
否则 Redis List（LPUSH/BRPOP 语义轮询）—— 保证异步链路在任何环境可运行。
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Optional

TOPIC = os.getenv("DATAAGENT_PULSAR_TOPIC", "persistent://dataagent/prod/dataagent-jobs")
DLQ_TOPIC = os.getenv("DATAAGENT_PULSAR_DLQ", TOPIC + "-dlq")
SUBSCRIPTION = os.getenv("DATAAGENT_PULSAR_SUBSCRIPTION", "dataagent-workers")
URL = os.getenv("DATAAGENT_PULSAR_URL", "pulsar://10.167.2.175:32160")

_producer = None
_client = None
_pulsar_ok: Optional[bool] = None

# memory 后端（GAP-14 探针/离线 worker 端到端用）：进程内 FIFO + nack 头部重投
_MEMQ: list[dict] = []


def _backend() -> str:
    """显式后端选择：DATAAGENT_QUEUE_BACKEND=memory 强制进程内队列（探针/测试）。

    缺省 ""=自动：Pulsar（若可用）→ Redis 兜底 → False（诚实失败）。
    memory 后端仅单进程有效——与内存仓储同一条纪律（必须 --workers 1）。
    """
    return os.getenv("DATAAGENT_QUEUE_BACKEND", "").strip().lower()


def mem_queue_depth() -> int:
    return len(_MEMQ)


def pulsar_available() -> bool:
    global _pulsar_ok
    if _pulsar_ok is None:
        if os.getenv("DATAAGENT_USE_PULSAR", "").lower() not in ("1", "true", "yes", "on"):
            _pulsar_ok = False
        else:
            try:
                import pulsar  # noqa: F401
                _pulsar_ok = True
            except Exception:  # noqa: BLE001
                _pulsar_ok = False
    return _pulsar_ok


def enqueue(task: dict) -> bool:
    """生产：显式后端（memory/redis）短路 → Pulsar 可用走真实 broker → Redis List 兜底。

    GAP-35（真机 E2E 实证）：enqueue 与 consume 的后端选择必须**对称**——
    QUEUE_BACKEND=redis 时若 enqueue 仍探测 Pulsar，消息会写进会被极速回收的
    话题，而消费端在 redis 兜底等待 → 通道断裂、任务永久 queued。
    显式 backend 是单一事实源：设了就两端同时短路。
    """
    body = json.dumps(task, ensure_ascii=False)
    if _backend() == "memory":
        _MEMQ.append(dict(task))
        return True
    if _backend() == "redis":
        cli = _redis()
        if cli is not None:
            cli.lpush("dataagent:queue:jobs", body)
            return True
        return False  # 显式 redis 但不可达：诚实失败（fail-fast 优于假入队）
    if pulsar_available():
        global _client, _producer
        try:
            import pulsar
            if _client is None:
                _client = pulsar.Client(URL)
            if _producer is None:
                _producer = _client.create_producer(TOPIC)
            _producer.send(body.encode("utf-8"))
            return True
        except Exception:  # noqa: BLE001  broker 不可达 → 兜底
            pass
    cli = _redis()
    if cli is not None:
        cli.lpush("dataagent:queue:jobs", body)
        return True
    return False


_SYNC_REDIS = None


def _redis():
    """同步 Redis 客户端（Worker 线程用；集群感知）。不可用返回 None。"""
    global _SYNC_REDIS
    if _SYNC_REDIS is not None:
        return _SYNC_REDIS
    url = os.getenv("DATAAGENT_REDIS_FALLBACK", "")
    if not url:
        return None
    try:
        import redis as _r
        from urllib.parse import urlparse, unquote
        u = urlparse(url)
        host, port = u.hostname or "127.0.0.1", u.port or 6379
        pwd = unquote(u.password) if u.password else None
        probe = _r.Redis(host=host, port=port, password=pwd,
                         decode_responses=True, socket_timeout=3)
        try:
            clustered = bool(probe.info("cluster").get("cluster_enabled"))
        except Exception:  # noqa: BLE001
            clustered = True
        try:
            probe.close()
        except Exception:  # noqa: BLE001
            pass
        if clustered:
            from redis.cluster import RedisCluster
            _SYNC_REDIS = RedisCluster(host=host, port=port, password=pwd,
                                       decode_responses=True, socket_timeout=3)
        else:
            _SYNC_REDIS = _r.Redis(host=host, port=port, password=pwd,
                                   decode_responses=True, socket_timeout=3)
        return _SYNC_REDIS
    except Exception:  # noqa: BLE001
        return None


class TaskMessage:
    """统一消息封装（Pulsar msg / Redis item 双形态）。"""

    def __init__(self, task: dict, *, ack_fn=None, nack_fn=None):
        self.task = task
        self._ack = ack_fn
        self._nack = nack_fn
        self.enqueued_at = time.time()

    def ack(self) -> None:
        if self._ack:
            self._ack()

    def nack(self) -> None:
        if self._nack:
            self._nack()


_consumer = None


def _dlq_policy(dlq_topic: str, max_redeliver: int):
    """DLQ 策略三代 API 兼容（GAP-27①：真机联调实证 pulsar-client 3.13 行为）。

    - 3.13+：`pulsar.ConsumerDeadLetterPolicy(...)`（Python 包装类，自带 .policy()，
      wrapper subscribe 内部调 policy() 转 _pulsar 配置——真机取证确认）；
    - ≤2.x 旧版：`pulsar.DeadLetterPolicy(...)` 构造器；
    - 都不在（异常版本）：返回 None（无 DLQ 语义，NACK 重投仍由 broker 默认处理）。
    """
    import pulsar

    if hasattr(pulsar, "ConsumerDeadLetterPolicy"):
        return pulsar.ConsumerDeadLetterPolicy(max_redeliver_count=max_redeliver,
                                               dead_letter_topic=dlq_topic)
    if hasattr(pulsar, "DeadLetterPolicy"):
        return pulsar.DeadLetterPolicy(max_redeliver_count=max_redeliver,
                                       dead_letter_topic=dlq_topic)
    return None


def consume(timeout_ms: int = 2000) -> Optional[TaskMessage]:
    """消费一条（同步；Worker 线程调用）。显式后端（memory/redis）短路 → Pulsar → Redis 兜底。"""
    global _client, _consumer
    if _backend() == "redis":
        cli = _redis()
        if cli is None:
            time.sleep(0.2)
            return None
        try:
            item = cli.brpop(["dataagent:queue:jobs"], timeout=max(1, min(timeout_ms // 1000, 2)))
        except Exception:  # noqa: BLE001  GAP-28：TimeoutError/ConnectionError → 空轮询
            return None
        if not item:
            return None
        _, body = item
        task = json.loads(body)
        return TaskMessage(task, ack_fn=lambda: None,
                           nack_fn=lambda: cli.lpush("dataagent:queue:jobs", body))
    if _backend() == "memory":
        if _MEMQ:
            task = _MEMQ.pop(0)
            # ack 已出队即确认；nack = 头部重投（保持原顺序，redelivery 语义）
            return TaskMessage(task, ack_fn=lambda: None,
                               nack_fn=lambda: _MEMQ.insert(0, task))
        time.sleep(0.2)
        return None
    if pulsar_available():
        global _consumer
        try:
            import pulsar
            if _client is None:
                _client = pulsar.Client(URL)
            if _consumer is None:
                policy = _dlq_policy(DLQ_TOPIC,
                                     int(os.getenv("DATAAGENT_PULSAR_MAX_REDELIVER", "3")))
                kwargs = {}
                if policy is not None:
                    kwargs["dead_letter_policy"] = policy
                    kwargs["negative_ack_redelivery_delay_ms"] = 30000
                # GAP-34 缓解（第十轮）：订阅起点可配——共享集群话题会被极速回收重建，
                # 新订阅默认 Latest 会错过重建前的消息；Earliest 让 worker 重挂后
                # 能追回积压（环境未禁回收时的自愈手段）。
                pos = os.getenv("DATAAGENT_PULSAR_INITIAL_POSITION", "").strip().lower()
                if pos == "earliest":
                    kwargs["initial_position"] = pulsar.InitialPosition.Earliest
                _consumer = _client.subscribe(
                    TOPIC, SUBSCRIPTION,
                    consumer_type=pulsar.ConsumerType.Shared, **kwargs)
            msg = _consumer.receive(timeout_millis=timeout_ms)
            task = json.loads(msg.data().decode("utf-8"))
            # GAP-29（真机联调发现）：ack_fn 必须闭包绑定当前 message——
            # 直接传 _consumer.acknowledge 会在 ack() 零参调用时缺实参（真机 TypeError 取证）
            return TaskMessage(
                task,
                ack_fn=lambda m=msg: _consumer.acknowledge(m),
                nack_fn=lambda m=msg: _consumer.negative_acknowledge(m),
            )
        except Exception:  # noqa: BLE001
            # GAP-32（真机联调发现）：话题可能被回收/重建——订阅失败必须**重置消费者**，
            # 让下一次 consume 重新 subscribe（自动重挂到重建后的话题），否则本进程会
            # 永久退化进 redis 空轮询、再也不回到 Pulsar（真机取证的双 Worker 假死根因）。
            _consumer = None
    cli = _redis()
    if cli is None:
        time.sleep(0.2)
        return None
    try:
        # GAP-28（真机联调发现）：socket_timeout=3 < brpop timeout 会抛
        # redis.TimeoutError —— 必须兜住（队列暂时不可达 = 诚实空轮询，不是故障上抛）
        item = cli.brpop(["dataagent:queue:jobs"], timeout=max(1, min(timeout_ms // 1000, 2)))
    except Exception:  # noqa: BLE001  TimeoutError/ConnectionError → 空轮询
        return None
    if not item:
        return None
    _, body = item
    task = json.loads(body)
    return TaskMessage(task, ack_fn=lambda: None,
                       nack_fn=lambda: cli.lpush("dataagent:queue:jobs", body))
