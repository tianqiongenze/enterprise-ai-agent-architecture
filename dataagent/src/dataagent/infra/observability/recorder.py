# -*- coding: utf-8 -*-
"""可观测性基座：Run 事件流与上下文决策追踪的 JSO\n 持久化（GAP-18）。

生产口径：审计与排障需要"进程重启后仍查得到"的事件/决策记录。M0 用本地 JSO\n
（append-only，一台机器即可跑通）；生产替换为日志聚合/列存只需换实现 —— 协议稳定：

    Recorder.record_run_events(run)            # 事件全量（按 event_id 幂等写）
    Recorder.record_decision(tenant, trace)    # ContextAssembler 决策追踪落盘
    Recorder.record_checkpoint(cp)             # 检查点快照（步骤状态可回看）

设计纪律：
- append-only 落盘（第 17 课"事实不可篡改"），读取按 ts 排序重放；
- 写失败不阻断主链路（观测面故障不得拖垮业务面），错误计数暴露于 stats.write_errors；
- 幂等去重按 event_id（同一 run 多次 record 不产生重复行）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

DEFAULT_EVENTS_FILE = "dataagent_events.jsonl"
DEFAULT_DECISIONS_FILE = "dataagent_decisions.jsonl"


class JsonlRecorder:
    """本地 JSO\n 记录器：events + decisions 两条流 + 检查点快照。"""

    def __init__(self, dirpath: "str | Path",
                 events_file: str = DEFAULT_EVENTS_FILE,
                 decisions_file: str = DEFAULT_DECISIONS_FILE):
        self.dir = Path(dirpath)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.dir / events_file
        self.decisions_path = self.dir / decisions_file
        self.stats = {"events_written": 0, "decisions_written": 0,
                      "checkpoints_written": 0, "write_errors": 0}
        self._seen_event_ids: set[str] = set()

    # ---------------- 写入（fail-safe：观测故障不阻断业务） ----------------

    def record_run_events(self, run) -> int:
        """Run 事件流写入 JSO\n（按 event_id 幂等），返回本次新写条数。"""
        n = 0
        try:
            with self.events_path.open("a", encoding="utf-8") as f:
                for e in sorted(run.events, key=lambda x: x.ts):
                    if e.event_id in self._seen_event_ids:
                        continue
                    self._seen_event_ids.add(e.event_id)
                    rec = {
                        "run_id": e.run_id,
                        "event_id": e.event_id,
                        "step_id": e.step_id,
                        "type": e.type.value,
                        "ts": e.ts,
                        "data": self._jsonable(e.data),
                    }
                    f.write(json.dumps(rec, ensure_ascii=False, default=str))
                    f.write("\n")
                    n += 1
            self.stats["events_written"] += n
        except OSError:
            self.stats["write_errors"] += 1
        return n

    def record_decision(self, tenant_id: str, trace: dict[str, Any],
                        *, contract: Optional[str] = None) -> None:
        """记录一次上下文装配决策（ContextSlice.decision_trace 的落盘形态）。"""
        try:
            payload = {"tenant_id": tenant_id, "contract": contract}
            payload.update(trace)
            with self.decisions_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False, default=str))
                f.write("\n")
            self.stats["decisions_written"] += 1
        except OSError:
            self.stats["write_errors"] += 1

    def record_slice(self, slice_, *, contract: Optional[str] = None) -> int:
        """ContextSlice 全量落盘：决策追踪 + 过滤原因（运营看板的数据源）。"""
        m = 0
        for tr in getattr(slice_, "decision_trace", []):
            self.record_decision(tr.get("tenant", "default"), tr, contract=contract)
            m += 1
        if slice_.filtered:
            self.record_decision(
                getattr(slice_, "tenant_hint", "default"),
                {"kind": "filtered", "items": [list(x) for x in slice_.filtered]},
                contract=contract,
            )
            m += 1
        return m

    def record_checkpoint(self, cp) -> str:
        """检查点独立快照：步骤状态序列可回看（第 25/41 课遗留的回补）。"""
        path = self.dir / (cp.run_id + ".checkpoint.json")
        try:
            snap = {
                "run_id": cp.run_id,
                "status": cp.status.value,
                "steps": [list(x) for x in cp.step_serial],
                "events_len": len(cp.event_serial),
                "budget": list(cp.budget),
                "created_at": cp.created_at,
            }
            path.write_text(json.dumps(snap, ensure_ascii=False, default=str),
                            encoding="utf-8")
            self.stats["checkpoints_written"] += 1
        except OSError:
            self.stats["write_errors"] += 1
        return str(path)

    # ---------------- 读取（重放/审计消费侧） ----------------

    def load_events(self, run_id: Optional[str] = None) -> list[dict]:
        return self._load(self.events_path, run_id)

    def load_decisions(self, tenant_id: Optional[str] = None) -> list[dict]:
        return self._load(self.decisions_path, tenant_id, key="tenant_id")

    def _load(self, path: Path, filter_val: Optional[str],
              key: str = "run_id") -> list[dict]:
        if not path.exists():
            return []
        out: list[dict] = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue  # 坏行跳过：append 文件可能被并发截断，诚实面对不抛
            if filter_val is None or rec.get(key) == filter_val:
                out.append(rec)
        return sorted(out, key=lambda r: r.get("ts", 0))

    @staticmethod
    def _jsonable(data: Any) -> Any:
        try:
            json.dumps(data, ensure_ascii=False)
            return data
        except (TypeError, ValueError):
            return {k: str(v) for k, v in data.items()}
