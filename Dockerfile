# bili-scribe Docker 镜像
# 开发和生产统一入口：bili-scribe serve
# 开发：.venv/bin/bili-scribe serve（无需 Docker）
# 生产：docker run（HTTP API + 前端 UI）

FROM python:3.12-slim-bookworm

LABEL org.opencontainers.image.title="bili-scribe"
LABEL org.opencontainers.image.description="B站视频字幕提取 + Whisper 本地语音转录 HTTP API"
LABEL org.opencontainers.image.version="1.0.0"

# ── 系统依赖 ──
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# ── 应用目录 ──
WORKDIR /app

# ── Python 依赖 ──
# 先复制依赖文件，利用 Docker 层缓存
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    "faster-whisper>=1.0.0" \
    "fastapi>=0.141.0" \
    "uvicorn>=0.52.0"

# ── 源码 ──
COPY src/ ./src/

# ── 输出和任务持久化目录 ──
RUN mkdir -p /app/out /app/tasks

# ── 非 root 用户 ──
RUN useradd --create-home --shell /bin/bash whisper && \
    chown -R whisper:whisper /app
USER whisper

# ── 环境变量 ──
ENV BILI_SCRIBE_OUTPUT_DIR=/app/out
ENV BILI_SCRIBE_TASKS_DIR=/app/tasks
ENV PYTHONUNBUFFERED=1
# BILI_SCRIBE_PASSWORD: 设置 HTTP Basic Auth 密码（不设置则不启用认证）
# 通过 docker run -e 或 docker-compose environment 传入

# ── 健康检查（健康端点不拦截，无需密码） ──
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')" || exit 1

# ── 端口 ──
EXPOSE 8000

# ── 入口（与开发环境完全一致） ──
CMD ["python", "-m", "src.cli.main", "serve", "--host", "0.0.0.0", "--port", "8000"]