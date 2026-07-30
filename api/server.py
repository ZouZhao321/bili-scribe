"""Bilibili Transcript API — FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.routes.health import router as health_router
from api.routes.video import router as video_router
from api.worker import worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: start background worker. Shutdown: stop worker."""
    worker.start()
    yield
    worker.stop()


app = FastAPI(
    title="Bilibili Transcript API",
    description="B站视频字幕提取 + Whisper 本地语音转录服务的 HTTP API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Register routers
app.include_router(health_router, prefix="/api/v1")
app.include_router(video_router, prefix="/api/v1")


@app.get("/")
async def root():
    return {"status": "ok", "service": "bilibili-transcript-api"}