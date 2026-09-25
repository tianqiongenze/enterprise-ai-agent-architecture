# DataAgent 部署与环境配置中心

> 这节课统一收口环境配置（Config/Secret），并明确 10.167.2.175/176 K8S 集群中各基础设施的接入方式。
> 环境变量以 `DATAAGENT_` 前缀暴露给应用；生产值由 Nacos / K8S Secret 注入，本文件只提供**默认/本地离线**取值。

## 1. 基础设施端点（真实 K8S 集群 infra 命名空间）

| 中间件 | 集群内 Service | 本机可达 (NodePort) | 端口/凭据 (探测确认) |
|--------|----------------|---------------------|----------------------|
| **Pulsar** (异步任务队列) | `infra/pulsar` | `10.167.2.175:32160` (Pulsar) / `:32679` (Admin) | 无认证；tenant `dataagent`、ns `dataagent/prod` 已建 |
| **CockroachDB** (关系库=Postgres 兼容) | `infra/cockroachdb` | `10.167.2.175:30257` | 用户 `root`，无密码（开发）；生产用证书 |
| **Redis** (缓存/会话/分布式锁) | `infra/redis` | `10.167.2.175:30090~30092` | requirepass `difyai123456` (开发) |
| **NebulaGraph** (经营血缘/关系图) | `infra/nebula-graphd` | `10.167.2.175` (Graph 9669) | 见 `nebula` 连接串 |
| **Milvus** (向量召回) | `infra/milvus` | `10.167.2.175:30909` (gRPC 19530) | attu 管理 31893 |
| **MinIO** (Artifact/BLOB) | `infra/milvus-minio` | `10.167.2.175:9000` | — |
| Nacos (配置/注册) | `infra/nacos` | `10.167.2.175:30910` | 无认证/开发 |

> 说明：CockroachDB 提供 **PostgreSQL 兼容协议**，故下面的 `DATABASE_URL` 使用驱动 `cockroachdb://` 或 `postgresql://` 均可；
> 驱动库统一用异步 `asyncpg`（对 CRDB 走 `postgresql` 协议）。

## 2. 环境变量（默认值=本地离线）

```dotenv
# ===== LLM Runtime =====
DATAAGENT_MODEL_DEFAULT=luna
DATAAGENT_MODEL_FALLBACK=default
DATAAGENT_MAX_ATTEMPTS=3
DATAAGENT_TIMEOUT_S=60

# ===== 基础设施（本地离线时可用内存实现；生产覆盖为下列真实端点）=====
DATAAGENT_DATABASE_URL=postgresql://root@10.167.2.175:30257/dataagent?sslmode=disable
DATAAGENT_REDIS_URL=redis://:difyai123456@10.167.2.175:30091/0
DATAAGENT_PULSAR_URL=pulsar://10.167.2.175:32160
DATAAGENT_PULSAR_TENANT=dataagent
DATAAGENT_PULSAR_NS=prod
DATAAGENT_PULSAR_TOPIC=dataagent-jobs
DATAAGENT_NEBULA_ADDR=10.167.2.175:9669
DATAAGENT_MILVUS_URI=http://10.167.2.175:30909
DATAAGENT_MINIO_ENDPOINT=10.167.2.175:9000

# ===== 服务 =====
DATAAGENT_API_HOST=0.0.0.0
DATAAGENT_API_PORT=8000
DATAAGENT_GRANIAN_THREADS=8
DATAAGENT_GRANIAN_WORKERS=2
```

## 3. 三级配置策略（SDD 交付物）

| 环境 | 配置来源 | 用途 |
|------|----------|------|
| local | `.env`/默认值（内存实现） | 离线开发/演示/单测 |
| staging | Nacos + K8S ConfigMap | 联调、灰度候选评测 |
| prod | K8S Secret + Nacos(加密) | 生产，多租户、百万并发 |

> 原则：**配置注入**而非硬编码；密钥只在 Secret/配置中心，不入库不入镜像（GB/T 安全基线）。
> 这与 `configs/` 中按环境拆分一致。