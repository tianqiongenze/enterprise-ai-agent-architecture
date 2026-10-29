# -*- coding: utf-8 -*-
"""运营通知 sink（GAP-19a）：默认 Log 实现只打印不外发——演示诚实；生产替换为邮件/IM 适配器。"""
from __future__ import annotations

import json
import time
from typing import Any


class LogNotificationSink:
    """控制台/日志通知：sweep 的升级与过期事件落日志，供日志聚合采集。

    fail-safe：notify 抛错由调用方（sweep）兜住——通知故障不得阻断巡检。
    """

    def __init__(self, prefix: str = "[notify]"):
        self.prefix = prefix
        self.sent: list[dict[str, Any]] = []  # 便于测试与审计回看

    def notify(self, kind: str, payload: dict[str, Any]) -> None:
        rec = {"kind": kind, "ts": time.time(), **payload}
        self.sent.append(rec)
        print(f"{self.prefix} {kind}: {json.dumps(payload, ensure_ascii=False)}", flush=True)


class WebhookNotificationSink:
    """Webhook 通知（第七轮真实环境验证）：审批升级/过期 POST 到 IM/网关的 hook URL。

    - 真实 IM（企业微信/钉钉/飞书群机器人）都是 webhook 形态——本实现是**通用适配点**，
      换 IM 只改 payload 包装器；
    - 超时 + 2 次重试 + 最终 fail-safe（调用方 sweep 已兜底，这里保证不抛）；
    - 每次投递记录 {kind, status, attempts} 便于审计与探针断言。
    """

    def __init__(self, url: str, *, timeout_s: float = 5.0, retries: int = 2,
                 prefix: str = "[notify-webhook]"):
        self.url = url
        self.timeout_s = timeout_s
        self.retries = retries
        self.prefix = prefix
        self.sent: list[dict[str, Any]] = []

    def notify(self, kind: str, payload: dict[str, Any]) -> None:
        import urllib.request

        body = json.dumps({"kind": kind, "ts": time.time(), **payload},
                          ensure_ascii=False).encode("utf-8")
        last_err: Optional[str] = None
        for attempt in range(1, self.retries + 2):
            try:
                req = urllib.request.Request(
                    self.url, data=body,
                    headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                    status = resp.status
                self.sent.append({"kind": kind, "status": status, "attempts": attempt})
                print(f"{self.prefix} {kind} → {self.url} [{status}] (attempt {attempt})", flush=True)
                return
            except Exception as e:  # noqa: BLE001
                last_err = f"{type(e).__name__}: {e}"
                time.sleep(0.3 * attempt)
        self.sent.append({"kind": kind, "status": "failed", "attempts": self.retries + 1,
                          "error": last_err})
        print(f"{self.prefix} {kind} → 投递失败(已放弃): {last_err}", flush=True)
