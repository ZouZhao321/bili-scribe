"""bili-scribe API — FastAPI 应用入口。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.web.routes.health import router as health_router
from src.web.routes.tasks import router as tasks_router
from src.web.routes.transcribe import router as transcribe_router
from src.web.routes.video import router as video_router
from src.web.worker import worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    """管理应用生命周期。

    启动时启动后台转录工作者，关闭时执行优雅关闭。

    参数：
        app: FastAPI 应用实例。

    生成：
        None: 在上下文管理器激活期间应用运行。
    """
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

# 注册路由
app.include_router(health_router, prefix="/api/v1")
app.include_router(video_router, prefix="/api/v1")
app.include_router(transcribe_router, prefix="/api/v1")
app.include_router(tasks_router, prefix="/api/v1")


@app.get("/")
async def root():
    """根端点 — 返回服务状态。

    返回：
        dict: 服务名称和状态指示。
    """
    return {"status": "ok", "service": "bili-scribe-api"}
