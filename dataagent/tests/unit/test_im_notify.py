# -*- coding: utf-8 -*-
"""R10 真实 IM 通知测试：企业微信/飞书/钉钉 wire-format 精确断言 + 环境工厂 + 真实本地 sink 实投。"""
import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from dataagent.infra.observability.notify import (
    IMNotificationSink, LogNotificationSink, WebhookNotificationSink, sink_from_env,
)


class TestWireFormat:
    def test_wecom_exact(self):
        s = IMNotificationSink("http://x", "wecom")
        body = s.build_body("approval_requested", {"approval_id": "a1"})
        assert body["msgtype"] == "markdown"
        assert "approval_requested" in body["markdown"]["content"]

    def test_feishu_exact(self):
        s = IMNotificationSink("http://x", "feishu")
        body = s.build_body("approval_requested", {"approval_id": "a1"})
        assert body["msg_type"] == "text" and "approval_requested" in body["content"]["text"]

    def test_dingtalk_exact(self):
        s = IMNotificationSink("http://x", "dingtalk")
        body = s.build_body("approval_requested", {"approval_id": "a1"})
        assert body["msgtype"] == "markdown" and body["markdown"]["title"]

    def test_generic_backward_compatible(self):
        s = IMNotificationSink("http://x", "generic")
        body = s.build_body("k", {"a": 1})
        assert body["kind"] == "k" and body["a"] == 1

    def test_unknown_provider_rejected(self):
        with pytest.raises(ValueError):
            IMNotificationSink("http://x", "slack")


class TestFactory:
    def test_default_log(self, monkeypatch):
        monkeypatch.delenv("DATAAGENT_IM_SINK", raising=False)
        monkeypatch.delenv("DATAAGENT_IM_WEBHOOK_URL", raising=False)
        assert isinstance(sink_from_env(), LogNotificationSink)

    def test_env_im(self, monkeypatch):
        monkeypatch.setenv("DATAAGENT_IM_SINK", "im")
        monkeypatch.setenv("DATAAGENT_IM_PROVIDER", "wecom")
        monkeypatch.setenv("DATAAGENT_IM_WEBHOOK_URL", "http://x")
        s = sink_from_env()
        assert isinstance(s, IMNotificationSink) and s.provider == "wecom"


class TestRealDelivery:
    """真实投递：本地 HTTP sink 收包并按各家 schema 校验（hook_receiver 同形态）。"""

    def _start_sink(self, received: list):
        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                received.append(json.loads(self.rfile.read(n)))
                self.send_response(200); self.end_headers(); self.wfile.write(b"{}")
            def log_message(self, *a): pass
        srv = HTTPServer(("127.0.0.1", 0), H)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
        return srv, port, t

    @pytest.mark.parametrize("provider,check", [
        ("wecom", lambda b: b["msgtype"] == "markdown"),
        ("feishu", lambda b: b["msg_type"] == "text"),
        ("dingtalk", lambda b: b["msgtype"] == "markdown" and "title" in b["markdown"]),
    ])
    def test_delivery_schema(self, provider, check):
        received: list = []
        srv, port, t = self._start_sink(received)
        try:
            s = IMNotificationSink(f"http://127.0.0.1:{port}", provider, retries=1)
            s.notify("approval_timeout", {"request_id": "r1"})
            time.sleep(0.1)
        finally:
            srv.shutdown()
        assert received and check(received[0]), f"{provider} wire-format 不符"
