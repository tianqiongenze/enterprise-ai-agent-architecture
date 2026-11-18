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
        last_err: str | None = None
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
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
                time.sleep(0.3 * attempt)
        self.sent.append({"kind": kind, "status": "failed", "attempts": self.retries + 1,
                          "error": last_err})
        print(f"{self.prefix} {kind} → 投递失败(已放弃): {last_err}", flush=True)


# ================= 真实 IM 适配（R10：企业微信/飞书/钉钉群机器人） =================
class IMNotificationSink:
    """真实 IM 群机器人通知：按 provider 生成各家**精确 wire-format**。

    - provider=wecom    企业微信群机器人：{"msgtype":"markdown","markdown":{"content":...}}
    - provider=feishu   飞书自定义机器人：{"msg_type":"text","content":{"text":...}}
    - provider=dingtalk 钉钉机器人：{"msgtype":"markdown","markdown":{"title":...,"text":...}}
    - provider=generic  通用 JSON（原 WebhookNotificationSink 形态，向后兼容）
    - 超时+重试+fail-safe 同 WebhookNotificationSink；每次投递记录 {status, attempts, body}
      便于按各家 wire-format 断言（对接 hook_receiver 校验）。

    用法（运营接入=一行 env，不改代码）：
      DATAAGENT_IM_SINK=im
      DATAAGENT_IM_PROVIDER=wecom|feishu|dingtalk|generic
      DATAAGENT_IM_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...
    """

    PROVIDERS = ("wecom", "feishu", "dingtalk", "generic")

    def __init__(self, url: str, provider: str = "generic", *,
                 timeout_s: float = 5.0, retries: int = 2, prefix: str = "[notify-im]"):
        provider = provider.lower()
        if provider not in self.PROVIDERS:
            raise ValueError(f"未知 IM provider: {provider}（可选 {self.PROVIDERS}）")
        self.url = url
        self.provider = provider
        self.timeout_s = timeout_s
        self.retries = retries
        self.prefix = prefix
        self.sent: list[dict[str, Any]] = []

    # ---- 各家 wire-format（保持与官方群机器人文档一字不差） ----
    def build_body(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        """纯函数：构造各家 wire-format（无网络，可确定性测试）。"""
        return self._body(kind, payload)

    def _body(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        text = f"**[{kind}]** " + json.dumps(payload, ensure_ascii=False)
        if self.provider == "wecom":
            return {"msgtype": "markdown", "markdown": {"content": text[:4096]}}
        if self.provider == "feishu":
            return {"msg_type": "text", "content": {"text": f"[{kind}] {json.dumps(payload, ensure_ascii=False)}"[:9500]}}
        if self.provider == "dingtalk":
            return {"msgtype": "markdown",
                    "markdown": {"title": kind[:20], "text": text[:18000]}}
        return {"kind": kind, "ts": time.time(), **payload}  # generic

    def notify(self, kind: str, payload: dict[str, Any]) -> None:
        import urllib.request

        body = json.dumps(self._body(kind, payload), ensure_ascii=False).encode("utf-8")
        last_err: str | None = None
        for attempt in range(1, self.retries + 2):
            try:
                req = urllib.request.Request(
                    self.url, data=body,
                    headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                    status = resp.status
                self.sent.append({"kind": kind, "status": status, "attempts": attempt,
                                  "provider": self.provider, "body": body.decode("utf-8")})
                print(f"{self.prefix} {kind} → {self.provider} [{status}] (attempt {attempt})", flush=True)
                return
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
                time.sleep(0.3 * attempt)
        self.sent.append({"kind": kind, "status": "failed", "attempts": self.retries + 1,
                          "provider": self.provider, "error": last_err})
        print(f"{self.prefix} {kind} → 投递失败(已放弃): {last_err}", flush=True)


def sink_from_env(prefix: str = "[notify]"):
    """工厂：按 env 构造通知 sink（运营接入=改 env，不改代码）。

    DATAAGENT_IM_SINK=log（默认，演示诚实）| webhook | im
    DATAAGENT_IM_PROVIDER / DATAAGENT_IM_WEBHOOK_URL 见 IMNotificationSink。
    """
    import os
    kind = os.getenv("DATAAGENT_IM_SINK", "log").lower()
    url = os.getenv("DATAAGENT_IM_WEBHOOK_URL", "")
    if kind == "im" and url:
        return IMNotificationSink(url, os.getenv("DATAAGENT_IM_PROVIDER", "generic"), prefix=prefix)
    if kind == "webhook" and url:
        return WebhookNotificationSink(url, prefix=prefix)
    return LogNotificationSink(prefix=prefix)
