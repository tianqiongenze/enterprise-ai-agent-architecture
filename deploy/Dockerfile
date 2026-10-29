FROM python:3.12-slim

WORKDIR /app

# 依赖先装(利用缓存)；第七轮起生产真实中间件驱动常驻（Redis/Pulsar 真实联调已验收）
COPY services/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir "redis>=5.0" "pulsar-client>=3.4"

# 安装服务层与内核
COPY services/ ./services/
COPY dataagent/ ./dataagent/
COPY scripts/ ./scripts/
RUN pip install --no-cache-dir ./services ./dataagent

EXPOSE 8000

# 默认以 Granian(全异步)启动 Litestar API；覆盖 command 可跑 worker
# 注意：granian 2.x 用 --host/--port（探针实测 -b 已不被接受，见 docs/12 GAP-24）
CMD ["granian", "--interface", "asgi", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "2", "--threads", "8", "--loop", "rloop", "services.api.asgi:app"]