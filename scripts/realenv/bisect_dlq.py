import json
import os

os.environ["DATAAGENT_USE_PULSAR"] = "1"
import pulsar  # noqa: E402

URL = "pulsar://pulsar-broker.infra.svc:6650"
TOPIC = "persistent://public/default/dataagent-probe"
cli = pulsar.Client(URL)

print("--- A: 仅 negative_ack_redelivery_delay_ms ---", flush=True)
c = cli.subscribe(TOPIC, "bisect-e", consumer_type=pulsar.ConsumerType.Shared,
                  negative_ack_redelivery_delay_ms=30000,
                  initial_position=pulsar.InitialPosition.Earliest)
try:
    m = c.receive(timeout_millis=4000)
    print("A: 收到", m.data().decode()[:40], flush=True)
    c.acknowledge(m)
except Exception as e:  # noqa: BLE001
    print("A: 超时/异常", type(e).__name__, str(e)[:80], flush=True)

print("--- B: 仅 dead_letter_policy ---", flush=True)
dlq = pulsar.DeadLetterPolicy(max_redeliver_count=3,
                              dead_letter_topic=TOPIC + "-dlq")
c = cli.subscribe(TOPIC, "bisect-f", consumer_type=pulsar.ConsumerType.Shared,
                  dead_letter_policy=dlq,
                  initial_position=pulsar.InitialPosition.Earliest)
try:
    m = c.receive(timeout_millis=4000)
    print("B: 收到", m.data().decode()[:40], flush=True)
    c.acknowledge(m)
except Exception as e:  # noqa: BLE001
    print("B: 超时/异常", type(e).__name__, str(e)[:80], flush=True)

print("--- C: 完整参数复刻（DLQ+negack）---", flush=True)
c = cli.subscribe(TOPIC, "bisect-g", consumer_type=pulsar.ConsumerType.Shared,
                  dead_letter_policy=dlq,
                  negative_ack_redelivery_delay_ms=30000,
                  initial_position=pulsar.InitialPosition.Earliest)
try:
    m = c.receive(timeout_millis=4000)
    print("C: 收到", m.data().decode()[:40], flush=True)
    c.acknowledge(m)
except Exception as e:  # noqa: BLE001
    print("C: 超时/异常", type(e).__name__, str(e)[:80], flush=True)
cli.close()
print("BISECT DONE", flush=True)
