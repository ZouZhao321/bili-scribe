# bili-scribe Docker 镜像
# 生产环境：HTTP API 服务
# 开发环境：直接源码运行 CLI（不经过 Docker）

FROM python:3.12-slim-bookworm

LABEL org.opencontainers.image.title="bili-scribe"
LABEL org.opencontainers.image.description="B站视频字幕提取 + Whisper 本地语音转录 HTTP API"
LABEL org.opencontainers.image.version="1.0.0"

# ── 系统依赖 ──
# 使用腾讯云镜像加速
# ffmpeg: DASH 音频流不可用时的 FLV → 音频提取回退
RUN sed -i 's/deb.debian.org/mirrors.cloud.tencent.com/g' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# ── 应用目录 ──
WORKDIR /app

# ── Python 依赖 ──
# 先复制依赖文件，利用 Docker 层缓存
# 使用腾讯云 PyPI 镜像加速
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip \
    -i https://mirrors.cloud.tencent.com/pypi/simple && \
    pip install --no-cache-dir \
    -i https://mirrors.cloud.tencent.com/pypi/simple \
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

# ── 健康检查 ──
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')" || exit 1

# ── 端口 ──
EXPOSE 8000

# ── 入口 ──
CMD ["uvicorn", "src.web.server:app", "--host", "0.0.0.0", "--port", "8000"]