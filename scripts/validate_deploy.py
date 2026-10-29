# -*- coding: utf-8 -*-
"""部署清单校验（对标参照工程 validate_manifests.py 的"硬约束清单"纪律）。

部署物也是交付物——Dockerfile/k8s/helm 的每个错误都是"部署时才爆炸"的延期缺陷
（GAP-24：k8s 里残留 granian 旧参数 `-b`，与 Dockerfile 同源问题，部署必挂）。
本脚本把部署纪律变成 CI 可拦的门禁：

  T1  YAML 可解析且三要素齐备（apiVersion/kind/metadata.name）
  T2  Deployment 规范：镜像存在、资源 requests/limits、selector 与模板标签一致
  T3  api Deployment：granian 参数合法（--host/--port，禁止 -b/--http2——GAP-24）
      + readiness/liveness 探针齐备
  T4  worker Deployment：入口为 python -m services.worker.main
  T5  Service：selector 匹配、端口映射存在
  T6  纪律门禁：内存仓储时代 HPA 必须注释停用（docs/11；参照工程同风格）
  T7  Helm：Chart.yaml 元数据 + values 可解析
  T8  秘密卫生：清单中不得出现明文口令（一律 secretRef）
  T9  ConfigMap：关键 env 键存在（DATAAGENT_* 前缀抽查）

用法：python scripts/validate_deploy.py → 退出码 0/1；逐项打印 ✓/✗。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEPLOY = ROOT / "deploy"

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, fn) -> None:
    try:
        fn()
        RESULTS.append((name, True, ""))
    except AssertionError as e:
        RESULTS.append((name, False, str(e)))
    except Exception as e:  # noqa: BLE001
        RESULTS.append((name, False, f"{type(e).__name__}: {e}"))


def _assert(cond, detail=""):
    if not cond:
        raise AssertionError(f"实际={detail}")


def load_docs(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    # 去掉整段注释块（如被停用的 HPA）后再解析
    stripped = "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("#")
    )
    return [d for d in yaml.safe_load_all(stripped) if d]


def main() -> int:
    dockerfile = (DEPLOY / "Dockerfile").read_text(encoding="utf-8")
    k8s_files = sorted((DEPLOY / "k8s").glob("*.yaml"))
    all_docs: dict[str, list[dict]] = {f.name: load_docs(f) for f in k8s_files}
    flat = [(fn, d) for fn, docs in all_docs.items() for d in docs]
    deployments = [(fn, d) for fn, d in flat if d.get("kind") == "Deployment"]
    services = [d for _, d in flat if d.get("kind") == "Service"]

    # ---- T1 YAML 三要素 ----
    for fn, d in flat:
        check(f"T1 {fn}: {d.get('kind')}/{d.get('metadata', {}).get('name')} 三要素",
              lambda d=d: _assert(d.get("apiVersion") and d.get("kind")
                                  and d.get("metadata", {}).get("name"), d.get("metadata")))

    # ---- T2 Deployment 规范 ----
    for fn, d in sorted(deployments):
        name = d["metadata"]["name"]
        spec = d["spec"]
        template = spec["template"]
        containers = template["spec"]["containers"]
        check(f"T2 {name}: 镜像存在", lambda c=containers: _assert(
            all(c0.get("image") for c0 in c), [c0.get("name") for c0 in c]))
        check(f"T2 {name}: 资源 requests/limits", lambda c=containers: _assert(
            all(c0.get("resources", {}).get("requests") and c0["resources"].get("limits")
                for c0 in c), "缺 resources"))
        check(f"T2 {name}: selector 与模板标签一致", lambda s=spec: _assert(
            s["selector"]["matchLabels"].items() <= s["template"]["metadata"]["labels"].items(),
            (s["selector"], s["template"]["metadata"]["labels"])))

    # ---- T3 api Deployment：granian 参数 + 探针（GAP-24 同源缺陷守门） ----
    api_docs = [d for fn, d in deployments if d["metadata"]["name"] == "dataagent-api"]
    if api_docs:
        api = api_docs[0]
        cmd = " ".join(api["spec"]["template"]["spec"]["containers"][0].get("command", []))
        check("T3 api: granian 使用 --host/--port（禁止旧参数 -b）",
              lambda: (_assert("--host" in cmd and "--port" in cmd, cmd),
                       _assert("-b " not in cmd and not cmd.startswith("-b"), cmd)))
        check("T3 api: 禁用 --http2（未经验证的组合，GAP-24 同源）",
              lambda: _assert("--http2" not in cmd, cmd))
        check("T3 api: 应用路径 services.api.asgi:app",
              lambda: _assert("services.api.asgi:app" in cmd, cmd))
        cs = api["spec"]["template"]["spec"]["containers"][0]
        check("T3 api: readiness+liveness 探针齐备", lambda: _assert(
            cs.get("readinessProbe") and cs.get("livenessProbe"), list(cs.keys())))

    # ---- T4 worker 入口 ----
    worker_docs = [d for fn, d in deployments if d["metadata"]["name"] == "dataagent-worker"]
    if worker_docs:
        wcmd = " ".join(worker_docs[0]["spec"]["template"]["spec"]["containers"][0].get("command", []))
        check("T4 worker: 入口 python -m services.worker.main",
              lambda: _assert("python -m services.worker.main" in wcmd or
                              "-m services.worker.main" in wcmd, wcmd))

    # ---- T5 Service ----
    for svc in services:
        name = svc["metadata"]["name"]
        check(f"T5 Service {name}: selector 与端口存在", lambda s=svc: _assert(
            s["spec"].get("selector") and s["spec"].get("ports"), s["spec"].keys()))

    # ---- T6 HPA 纪律（内存仓储时代必须停用） ----
    check("T6 纪律: HPA 显式注释停用（docs/11；启用前需持久化+分布式+多副本测试全绿）",
          lambda: _assert(
              all(d.get("kind") != "HorizontalPodAutoscaler" for _, d in flat),
              [d["kind"] for _, d in flat if d.get("kind") == "HorizontalPodAutoscaler"]))

    # ---- T7 Helm ----
    chart = DEPLOY / "helm" / "Chart.yaml"
    check("T7 helm: Chart.yaml name+version", lambda: _assert(
        (c := yaml.safe_load(chart.read_text(encoding="utf-8"))) and c.get("name") and c.get("version")))
    for values in ("values.yaml", "values-prod.yaml"):
        vf = DEPLOY / "helm" / values
        check(f"T7 helm: {values} 可解析", lambda vf=vf: _assert(
            isinstance(yaml.safe_load(vf.read_text(encoding="utf-8")), dict)))

    # ---- T8 秘密卫生 ----
    def _no_plaintext_secret():
        for fn, d in flat:
            if d.get("kind") == "Secret":
                continue  # Secret 资源的 stringData 是密钥的合法归宿（真实生产换 Vault，见文件注释）
            text = yaml.safe_dump(d, allow_unicode=True)
            for i, line in enumerate(text.splitlines()):
                if re.search(r"(?i)(password|secret|token)\s*:\s*\S+", line) \
                        and "secretRef" not in line and "secretName" not in line \
                        and not line.strip().startswith("#"):
                    raise AssertionError(f"{fn}({d.get('kind')}): {line.strip()[:80]}")
    check("T8 秘密卫生: 非 Secret 资源无明文口令（一律 secretRef/Secret 承载）", _no_plaintext_secret)

    # ---- T9 ConfigMap 关键 env 抽查 ----
    cms = [d for _, d in flat if d.get("kind") == "ConfigMap"]
    if cms:
        keys = set()
        for cm in cms:
            data = cm.get("data", {}) or {}
            keys |= set(data.keys())
        check("T9 ConfigMap: 含 DATAAGENT_ 前缀配置", lambda: _assert(
            any(k.startswith("DATAAGENT_") for k in keys), sorted(keys)[:8]))

    # ---- 汇总 ----
    print("=" * 72)
    print(f"部署清单校验：Dockerfile + {len(k8s_files)} 个 k8s 文件 + helm（硬约束 {len(RESULTS)} 项）")
    print("=" * 72)
    for name, ok, detail in RESULTS:
        print(f"  {'✓ PASS' if ok else '✗ ' + detail}  {name}")
    print("-" * 72)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"通过 {passed}/{len(RESULTS)}")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
