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
    """生产：Pulsar 可用走真实 broker；否则 Redis List。"""
    body = json.dumps(task, ensure_ascii=False)
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


def consume(timeout_ms: int = 2000) -> Optional[TaskMessage]:
    """消费一条（同步；Worker 线程调用）。Pulsar 优先（NACK+DLQ），Redis 兜底。"""
    global _client, _consumer
    if pulsar_available():
        try:
            import pulsar
            if _client is None:
                _client = pulsar.Client(URL)
            if _consumer is None:
                _consumer = _client.subscribe(
                    TOPIC, SUBSCRIPTION,
                    consumer_type=pulsar.ConsumerType.Shared,
                    dead_letter_policy=pulsar.DeadLetterPolicy(
                        max_redeliver_count=int(os.getenv("DATAAGENT_PULSAR_MAX_REDELIVER", "3")),
                        dead_letter_topic=DLQ_TOPIC),
                    negative_ack_redelivery_delay_ms=30000,
                )
            msg = _consumer.receive(timeout_millis=timeout_ms)
            task = json.loads(msg.data().decode("utf-8"))
            return TaskMessage(
                task,
                ack_fn=_consumer.acknowledge,
                nack_fn=_consumer.negative_acknowledge,
            )
        except Exception:  # noqa: BLE001  broker 异常 → 兜底 Redis
            pass
    cli = _redis()
    if cli is None:
        time.sleep(0.2)
        return None
    item = cli.brpop(["dataagent:queue:jobs"], timeout=max(1, timeout_ms // 1000))
    if not item:
        return None
    _, body = item
    task = json.loads(body)
    return TaskMessage(task, ack_fn=lambda: None,
                       nack_fn=lambda: cli.lpush("dataagent:queue:jobs", body))
