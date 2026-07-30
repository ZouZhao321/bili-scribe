"""Pydantic data models for Bilibili Transcript API."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# ── Enums ──

class TranscriptMode(str, Enum):
    auto = "auto"
    subtitle = "subtitle"
    whisper = "whisper"
    both = "both"


class WhisperModel(str, Enum):
    tiny = "tiny"
    base = "base"
    small = "small"
    medium = "medium"
    large_v3 = "large-v3"


class OutputFormat(str, Enum):
    text = "text"
    timestamps = "timestamps"
    json = "json"


class TaskStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class ProgressPhase(str, Enum):
    queued = "queued"
    fetching_info = "fetching_info"
    downloading_audio = "downloading_audio"
    loading_model = "loading_model"
    transcribing = "transcribing"
    completed = "completed"
    failed = "failed"


class TranscriptSource(str, Enum):
    subtitle = "subtitle"
    whisper = "whisper"


# ── Sub-models ──

class SubtitleEntry(BaseModel):
    from_: float = Field(alias="from")
    to: float
    content: str


class UsageInfo(BaseModel):
    source: TranscriptSource
    model: str = ""
    duration_seconds: float = 0
    audio_duration: Optional[float] = None
    real_time_factor: Optional[float] = None


class AudioInfo(BaseModel):
    size_bytes: int = 0
    duration_seconds: float = 0


class ProgressInfo(BaseModel):
    phase: ProgressPhase
    percent: int = 0
    message: str = ""
    bytes_downloaded: Optional[int] = None
    bytes_total: Optional[int] = None


class PageInfo(BaseModel):
    page: int
    part: str
    cid: int


# ── Request models ──

class TranscribeRequest(BaseModel):
    url: str = Field(..., description="B站视频链接或BV号，支持 BV1xxx、av12345、b23.tv/xxx")
    mode: TranscriptMode = Field(default=TranscriptMode.auto, description="转录模式")
    model: WhisperModel = Field(default=WhisperModel.small, description="Whisper 模型大小")
    language: str = Field(default="zh", description="Whisper 语言提示")
    page: int = Field(default=0, ge=0, description="分 P 序号（0-indexed）")
    output_format: OutputFormat = Field(default=OutputFormat.text, description="输出格式")
    cookie: str = Field(default="", description="B站登录 Cookie")
    webhook: str = Field(default="", description="异步任务完成后的回调 URL")

    @field_validator("url")
    @classmethod
    def url_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("url 不能为空")
        return v.strip()


# ── Response models ──

class TranscriptResult(BaseModel):
    bvid: str
    title: str
    author: str = ""
    duration: int = 0
    source: TranscriptSource
    total_pages: int = 1
    current_page: int = 0
    entries: int = 0
    subtitles: list[SubtitleEntry] = []
    full_text: str = ""


class TranscribeResponse(BaseModel):

    task_id: str
    status: TaskStatus
    mode: str  # "sync" | "async"
    estimated_seconds: Optional[int] = None
    result: Optional[TranscriptResult] = None
    audio: Optional[AudioInfo] = None
    usage: Optional[UsageInfo] = None
    links: Optional[dict[str, str]] = None


class TaskProgress(BaseModel):
    phase: ProgressPhase
    percent: int = 0
    message: str = ""
    bytes_downloaded: Optional[int] = None
    bytes_total: Optional[int] = None


class TaskRequest(BaseModel):
    url: str
    model: str = "small"
    output_format: str = "text"


class TaskStatusResponse(BaseModel):
    task_id: str
    status: TaskStatus
    mode: str = ""
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    progress: TaskProgress
    request: Optional[TaskRequest] = None
    result: Optional[TranscriptResult] = None
    usage: Optional[UsageInfo] = None


class TaskSummary(BaseModel):
    task_id: str
    status: TaskStatus
    mode: str
    url: str
    model: str = "small"
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    progress: TaskProgress


class TaskListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    tasks: list[TaskSummary]


class HealthCheckItem(BaseModel):
    status: str  # "ok" | "error"
    message: str = ""


class HealthChecks(BaseModel):
    queue_worker: HealthCheckItem
    whisper_model: HealthCheckItem = HealthCheckItem(status="ok", message="未检查")
    disk_space: HealthCheckItem
    bilibili_api: HealthCheckItem = HealthCheckItem(status="ok", message="未检查")


class HealthResponse(BaseModel):
    status: str  # "ok" | "error"
    version: str = "1.0.0"
    uptime: float = 0
    whisper_models: list[str] = ["tiny", "base", "small", "medium", "large-v3"]
    default_model: str = "small"
    queue: dict[str, int] = {}
    checks: Optional[HealthChecks] = None


# ── Video info ──

class VideoInfoResponse(BaseModel):
    bvid: str
    title: str
    author: str = ""
    duration: int = 0
    duration_formatted: str = ""
    cover: str = ""
    description: str = ""
    total_pages: int = 1
    pages: list[PageInfo] = []
    has_subtitle: bool = False
    subtitle_languages: list[str] = []


# ── Error ──

class ErrorResponse(BaseModel):
    error: str
    message: str
    details: Optional[Any] = None


# ── Webhook ──

class WebhookPayload(BaseModel):
    event: str  # "transcription.completed" | "transcription.failed"
    task_id: str
    status: TaskStatus
    result: Optional[TranscriptResult] = None
    usage: Optional[UsageInfo] = None
    error: Optional[str] = None
    message: Optional[str] = None