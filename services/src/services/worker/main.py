# -*- coding: utf-8 -*-
"""Worker：从 Pulsar 消费异步分析任务并执行 DataAgent 内核。

生产环境由多个 Worker 副本水平扩展，消费 `persistent://dataagent/prod/dataagent-jobs`；
本地(未启用 Pulsar)降级为内存队列轮询，保证可离线演示/测试。
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "dataagent", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from services.shared.runtime import InfraProvider, Settings


class AnalysisWorker:
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or Settings()
        self.infra = InfraProvider(self.settings)
        self._container = None

    def container(self):
        if self._container is None:
            from dataagent.app.container import DataAgentContainer, default_seed
            self._container = DataAgentContainer(seed_orders=default_seed())
        return self._container

    async def handle(self, task: dict) -> None:
        """执行一次分析任务，并写入可观测（Run Timeline）。"""
        query = task.get("query", "")
        tenant = task.get("tenant_id", "ten_a")
        c = self.container()
        run = c.analyze(query, tenant)
        print(f"[worker] task done run_id={run.run_id} status={run.status.value} steps={len(run.steps)}")

    async def run(self) -> None:
        print(f"[worker] consumer started (pulsar={self.settings.use_pulsar})")
        while True:
            task = await self.infra.poll(timeout_s=0.5)
            if task is None:
                continue
            try:
                await self.handle(task)
            except Exception as e:  # pragma: no cover
                print("[worker] error:", e)


def main() -> int:
    asyncio.run(AnalysisWorker().run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())