"""Bilibili Transcript API — FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.routes.health import router as health_router
from api.routes.video import router as video_router
from api.routes.transcribe import router as transcribe_router
from api.routes.tasks import router as tasks_router
from api.worker import worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage the application lifecycle.

    Starts the background transcription worker on startup and
    performs a graceful shutdown on teardown.

    Args:
        app: The FastAPI application instance.

    Yields:
        None: The application runs while the context manager is active.
    """
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
app.include_router(transcribe_router, prefix="/api/v1")
app.include_router(tasks_router, prefix="/api/v1")


@app.get("/")
async def root():
    """Root endpoint — returns service status.

    Returns:
        dict: Service name and status indicator.
    """
    return {"status": "ok", "service": "bilibili-transcript-api"}