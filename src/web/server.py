"""bili-scribe API — FastAPI 应用入口。"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.web.auth import BasicAuthMiddleware
from src.web.queue import queue
from src.web.routes.health import router as health_router
from src.web.routes.tasks import router as tasks_router
from src.web.routes.transcribe import router as transcribe_router
from src.web.routes.video import router as video_router
from src.web.storage import storage
from src.web.worker import worker

# 静态文件目录（相对于本文件）
STATIC_DIR = Path(__file__).parent / "static"


def _check_whisper_models() -> None:
    """检查 Whisper 模型是否已下载。"""
    cache_dir = Path.home() / ".cache" / "huggingface" / "hub"
    models_dir = cache_dir / "models--Systran--faster-whisper-base"

    if not models_dir.exists():
        print(
            "[server] ⚠️  Whisper 模型未下载，请先运行: bili-scribe init",
            file=__import__("sys").stderr,
        )
    else:
        print(
            "[server] Whisper base 模型已就绪",
            file=__import__("sys").stderr,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """管理应用生命周期。

    启动时恢复持久化任务，然后启动后台转录工作者。
    关闭时执行优雅关闭。

    参数：
        app: FastAPI 应用实例。

    生成：
        None: 在上下文管理器激活期间应用运行。
    """
    # 从磁盘恢复任务
    recovered = storage.recover(queue)
    print(f"[server] 从磁盘恢复 {recovered} 个任务", file=__import__("sys").stderr)

    # 检查 Whisper 模型
    _check_whisper_models()

    worker.start()
    yield
    worker.stop()


app = FastAPI(
    title="bili-scribe API",
    description="B站视频字幕提取 + Whisper 本地语音转录服务的 HTTP API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── 认证中间件（最先执行，密码未设置时自动跳过） ──
app.add_middleware(BasicAuthMiddleware)

# ── API 路由（先注册，优先级高于静态文件） ──
app.include_router(health_router, prefix="/api/v1")
app.include_router(video_router, prefix="/api/v1")
app.include_router(transcribe_router, prefix="/api/v1")
app.include_router(tasks_router, prefix="/api/v1")

# ── 前端 SPA（最后挂载，/ 指向 index.html） ──
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
