FROM python:3.12-slim

WORKDIR /app

# 依赖先装(利用缓存)；保留可选基础设施驱动注释，生产按需开
COPY services/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 可选：生产接入真实中间件时启用
# RUN pip install --no-cache-dir asyncpg redis pulsar-client nebula3 pymilvus

# 安装服务层与内核
COPY services/ ./services/
COPY dataagent/ ./dataagent/
COPY scripts/ ./scripts/
RUN pip install --no-cache-dir ./services ./dataagent

EXPOSE 8000

# 默认以 Granian(全异步)启动 Litestar API；覆盖 command 可跑 worker
CMD ["granian", "--interface", "asgi", "-b", "0.0.0.0:8000", \
     "--workers", "2", "--threads", "8", "--loop", "rloop", "--http2", \
     "services.api.asgi:app"]