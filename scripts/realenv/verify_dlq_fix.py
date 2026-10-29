import json
import os
import sys
import traceback

os.environ["DATAAGENT_USE_PULSAR"] = "1"
os.environ["DATAAGENT_PULSAR_URL"] = "pulsar://pulsar-broker.infra.svc:6650"
os.environ.pop("DATAAGENT_REDIS_FALLBACK", None)
sys.path.insert(0, "/app/services/src")

import pulsar  # noqa: E402
import inspect  # noqa: E402

print("pulsar client version marker: DLQBuilder?", hasattr(pulsar, "DeadLetterPolicyBuilder"), flush=True)
try:
    sig = inspect.signature(pulsar.Client.subscribe)
    print("subscribe params:", list(sig.parameters)[:14], flush=True)
except Exception as e:  # noqa: BLE001
    print("sig err:", e, flush=True)

from services.shared import queue as q  # noqa: E402

print("pulsar_available:", q.pulsar_available(), flush=True)
print("warmup:", q.consume(timeout_ms=1200), flush=True)
task = {"kind": "analysis", "query": "DLQ fix verify", "tenant_id": "ten_a",
        "user_id": "u1", "request_id": "real-pulsar-6"}
print("enqueue:", q.enqueue(task), flush=True)
try:
    msg = q.consume(timeout_ms=10000)
    print("consume:", msg is not None,
          "| request_id:", (msg.task.get("request_id") if msg else None), flush=True)
    if msg:
        msg.ack()
        print("ack done", flush=True)
except Exception:
    traceback.print_exc()
print("VERIFY DONE", flush=True)
