"""Locust 压测 v2 —— DataAgent API 真实部署（10.167.2.175:30080）。

v2 变更（GAP-35 压测收口）：
- on_startup 真实登录（CRDB 种子用户 admin）→ Bearer 鉴权头；
- 场景权重对齐真实流量画像：健康读 3 / 异步入队 3 / 任务中心读 2 / 管理面读 1 / 同步分析 1；
- 同步分析（FakeLlm 全链路 ~1-3s）为重请求，权重最低防打爆共享集群。

用法（仓库根）:
    python -m locust -f tests/load/locustfile.py --headless -u 10 -r 2 -t 90s \
        --host http://10.167.2.175:30080 --csv docs/15-data/locust --html docs/15-data/locust.html
"""
import random

from locust import HttpUser, between, task


class DataAgentUser(HttpUser):
    wait_time = between(0.2, 0.8)
    QUERIES = [
        "华东区本月 GMV 下滑原因诊断",
        "华南区转化率下降分析",
        "华北清库存建议",
    ]

    def on_start(self):
        r = self.client.post("/login", json={"username": "admin", "password": "admin123"})
        token = r.json().get("token", "")
        self.headers = {"Authorization": f"Bearer {token}"}

    @task(3)
    def healthz(self):
        self.client.get("/healthz", name="[public] /healthz")

    @task(3)
    def async_enqueue(self):
        q = random.choice(self.QUERIES)
        self.client.post("/v1/analysis", headers=self.headers,
                         json={"query": f"{q}（压测）", "tenant_id": "ten_a",
                               "user_id": "u1", "async_": True},
                         name="[biz] POST /v1/analysis async")

    @task(2)
    def tasks_list(self):
        self.client.get("/v1/admin/tasks", headers=self.headers,
                        name="[admin] GET /v1/admin/tasks")

    @task(1)
    def dashboard(self):
        self.client.get("/v1/admin/dashboard", headers=self.headers,
                        name="[admin] GET /v1/admin/dashboard")

    @task(1)
    def sync_analysis(self):
        q = random.choice(self.QUERIES)
        self.client.post("/v1/analysis", headers=self.headers,
                         json={"query": f"{q}（同步压测）", "tenant_id": "ten_a"},
                         name="[biz] POST /v1/analysis sync", timeout=30)
