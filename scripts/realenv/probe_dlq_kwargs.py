import json
import os
import traceback

import pulsar  # noqa: E402

URL = "pulsar://pulsar-broker.infra.svc:6650"
TOPIC = "persistent://public/default/dataagent-probe"
cli = pulsar.Client(URL)

policy = (pulsar.DeadLetterPolicyBuilder()
          .maxRedeliverCount(3)
          .deadLetterTopic(TOPIC + "-dlq")
          .build())
try:
    c = cli.subscribe(TOPIC, "verify-dlq-kw",
                      consumer_type=pulsar.ConsumerType.Shared,
                      dead_letter_policy=policy,
                      negative_ack_redelivery_delay_ms=30000,
                      initial_position=pulsar.InitialPosition.Earliest)
    print("subscribe OK", flush=True)
    m = c.receive(timeout_millis=6000)
    print("received:", m.data().decode()[:50], flush=True)
    c.acknowledge(m)
    print("ack done", flush=True)
except Exception:  # noqa: BLE001
    traceback.print_exc()
finally:
    cli.close()
print("PROBE DONE", flush=True)
