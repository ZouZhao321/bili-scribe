"""Bilibili Transcript API — FastAPI application entry point."""

from fastapi import FastAPI

app = FastAPI(
    title="Bilibili Transcript API",
    description="B站视频字幕提取 + Whisper 本地语音转录服务的 HTTP API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


@app.get("/")
async def root():
    return {"status": "ok", "service": "bilibili-transcript-api"}