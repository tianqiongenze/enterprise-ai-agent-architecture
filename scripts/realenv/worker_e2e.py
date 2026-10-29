import os
import sys

os.environ["DATAAGENT_USE_PULSAR"] = "1"
os.environ["DATAAGENT_PULSAR_URL"] = "pulsar://pulsar-broker.infra.svc:6650"
os.environ.pop("DATAAGENT_REDIS_FALLBACK", None)
os.environ["DATAAGENT_APPROVAL_MODE"] = "auto"
# 双布局陷阱：镜像内 dataagent/services 都是 src 布局，worker main 的相对 sys.path
# hack 在 src 布局下失效（层级 +1），会命中 site-packages 旧副本——显式插两条 src 路径
sys.path.insert(0, "/app/dataagent/src")
sys.path.insert(0, "/app/services/src")

from services.shared import queue as q  # noqa: E402
from services.worker import main as w  # noqa: E402

print("1) enqueue 真实任务（Pulsar）", flush=True)
task = {"kind": "analysis", "query": "华东区本月 GMV 下滑原因诊断（真实队列 e2e）",
        "tenant_id": "ten_a", "user_id": "u1", "request_id": "worker-e2e-1"}
assert q.enqueue(task) is True

print("2) worker.run_once() 消费+执行+ack", flush=True)
final = w.run_once(timeout_ms=10000)
print("   终态 =", final, flush=True)

assert final == "succeeded", f"期望 succeeded，实际 {final}"
print("WORKER E2E (real Pulsar → analysis → ack): ALL OK", flush=True)
