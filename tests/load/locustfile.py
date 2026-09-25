"""Locust 压测 —— DataAgent API (以 100 万并发为目标的架构压测)。

用法:
    locust -f tests/load/locustfile.py --host http://127.0.0.1:8000
    # 或 以 headless 模式跑冒烟:
    locust -f tests/load/locustfile.py --host http://127.0.0.1:8000 \
        --headless -u 200 -r 20 --run-time 30s --csv dataagent

测试矩阵（对齐 docs/06 审计 §2 Granian 参数与 §4 容量推演）:
- /healthz 只读健康
- POST /v1/analysis (同步) —— 短请求/低并发
- POST /v1/analysis (async_=true) —— 百万并发友好的入队路径（压测重点）
"""
import random
import time

from locust import HttpUser, between, events, task


class DataAgentAnalysisUser(HttpUser):
    """模拟企业租户用户提交经营分析。"""

    wait_time = between(0.05, 0.3)
    QUERIES = [
        "华东区本月 GMV 下滑原因诊断",
        "华南区转化率下降分析",
        "华北清库存建议",
        "GMV trend and refund rate",
    ]

    @task(1)
    def health(self) -> None:
        self.client.get("/healthz")

    @task(4)
    def submit_analysis_async(self) -> None:
        # 主打路径：异步入队(Pulsar)，返回 task_id —— 百万并发架构的核心
        self.client.post(
            "/v1/analysis",
            json={
                "query": random.choice(self.QUERIES),
                "tenant_id": random.choice(["ten_a", "ten_b"]),
                "async_": True,
            },
            name="POST /v1/analysis (async queue)",
        )

    @task(1)
    def submit_analysis_sync(self) -> None:
        # 同步路径：较慢，主要用于对比/低并发验证
        self.client.post(
            "/v1/analysis",
            json={
                "query": random.choice(self.QUERIES),
                "tenant_id": "ten_a",
                "async_": False,
            },
            name="POST /v1/analysis (sync)",
        )


# 事件：记录到 stdout，便于 CI 拉取吞吐统计
@events.test_start.add_listener
def on_test_start(environment, **_kwargs):
    print("[load] DataAgent 压测已启动。重点：POST /v1/analysis (async queue) —— 削峰路径。")


@events.test_stop.add_listener
def on_test_stop(environment, **_kwargs):
    stats = environment.runner.stats
    print(f"[load] 总请求 {stats.num_requests}，RPS {stats.total_rps:.1f}，"
          f"P50 {stats.total.get_response_time_percentile(0.5):.1f}ms "
          f"P95 {stats.total.get_response_time_percentile(0.95):.1f}ms "
          f"失败 {stats.num_failures}")