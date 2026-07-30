"""Tests for API Pydantic models (api/models.py)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from api.models import (
    AudioInfo,
    ErrorResponse,
    HealthResponse,
    OutputFormat,
    ProgressInfo,
    ProgressPhase,
    SubtitleEntry,
    TaskListResponse,
    TaskProgress,
    TaskStatus,
    TaskStatusResponse,
    TranscriptMode,
    TranscriptResult,
    TranscribeRequest,
    TranscribeResponse,
    TranscriptSource,
    UsageInfo,
    VideoInfoResponse,
    WhisperModel,
)


class TestEnums:
    """Test enum values."""

    def test_transcript_mode_values(self):
        assert TranscriptMode.auto.value == "auto"
        assert TranscriptMode.subtitle.value == "subtitle"
        assert TranscriptMode.whisper.value == "whisper"
        assert TranscriptMode.both.value == "both"

    def test_whisper_model_values(self):
        assert WhisperModel.tiny.value == "tiny"
        assert WhisperModel.small.value == "small"
        assert WhisperModel.large_v3.value == "large-v3"

    def test_task_status_values(self):
        assert TaskStatus.pending.value == "pending"
        assert TaskStatus.processing.value == "processing"
        assert TaskStatus.completed.value == "completed"
        assert TaskStatus.failed.value == "failed"

    def test_progress_phase_values(self):
        assert ProgressPhase.queued.value == "queued"
        assert ProgressPhase.transcribing.value == "transcribing"

    def test_output_format_values(self):
        assert OutputFormat.text.value == "text"
        assert OutputFormat.timestamps.value == "timestamps"
        assert OutputFormat.json.value == "json"

    def test_transcript_source_values(self):
        assert TranscriptSource.subtitle.value == "subtitle"
        assert TranscriptSource.whisper.value == "whisper"


class TestTranscribeRequest:
    """Test TranscribeRequest model."""

    def test_default_values(self):
        req = TranscribeRequest(url="BV1Gm421W75K")
        assert req.url == "BV1Gm421W75K"
        assert req.mode == TranscriptMode.auto
        assert req.model == WhisperModel.small
        assert req.language == "zh"
        assert req.page == 0
        assert req.output_format == OutputFormat.text
        assert req.cookie == ""
        assert req.webhook == ""

    def test_all_fields_set(self):
        req = TranscribeRequest(
            url="https://www.bilibili.com/video/BV1Gm421W75K",
            mode="whisper",
            model="medium",
            language="en",
            page=1,
            output_format="json",
            cookie="test_cookie",
            webhook="https://example.com/callback",
        )
        assert req.mode == TranscriptMode.whisper
        assert req.model == WhisperModel.medium
        assert req.language == "en"
        assert req.page == 1
        assert req.output_format == OutputFormat.json
        assert req.cookie == "test_cookie"
        assert req.webhook == "https://example.com/callback"

    def test_url_trimmed(self):
        req = TranscribeRequest(url="  BV1Gm421W75K  ")
        assert req.url == "BV1Gm421W75K"

    def test_empty_url_raises(self):
        with pytest.raises(ValidationError):
            TranscribeRequest(url="")

    def test_invalid_model_raises(self):
        with pytest.raises(ValidationError):
            TranscribeRequest(url="BV1xxx", model="invalid_model")

    def test_invalid_mode_raises(self):
        with pytest.raises(ValidationError):
            TranscribeRequest(url="BV1xxx", mode="invalid_mode")

    def test_invalid_page_negative(self):
        with pytest.raises(ValidationError):
            TranscribeRequest(url="BV1xxx", page=-1)

    def test_serialize_deserialize(self):
        req = TranscribeRequest(url="BV1Gm421W75K", mode="whisper", model="tiny")
        data = req.model_dump(mode="json")
        assert data["url"] == "BV1Gm421W75K"
        assert data["mode"] == "whisper"
        assert data["model"] == "tiny"

        # Deserialize back
        req2 = TranscribeRequest(**data)
        assert req2.url == req.url
        assert req2.mode == req.mode


class TestTranscriptResult:
    """Test TranscriptResult model."""

    def test_minimal(self):
        result = TranscriptResult(
            bvid="BV1xxx",
            title="Test",
            source="subtitle",
        )
        assert result.bvid == "BV1xxx"
        assert result.title == "Test"
        assert result.source == TranscriptSource.subtitle
        assert result.entries == 0
        assert result.subtitles == []

    def test_with_subtitles(self):
        result = TranscriptResult(
            bvid="BV1xxx",
            title="Test",
            source="whisper",
            entries=2,
            subtitles=[
                SubtitleEntry(**{"from": 0.0, "to": 3.5, "content": "你好"}),
                SubtitleEntry(**{"from": 3.5, "to": 8.0, "content": "世界"}),
            ],
            full_text="你好\n世界",
        )
        assert result.entries == 2
        assert len(result.subtitles) == 2
        assert result.subtitles[0].from_ == 0.0
        assert result.subtitles[0].content == "你好"
        assert result.full_text == "你好\n世界"


class TestSubtitleEntry:
    """Test SubtitleEntry model with alias."""

    def test_from_alias(self):
        """from_ should serialize to 'from' in JSON."""
        entry = SubtitleEntry(**{"from": 1.5, "to": 5.0, "content": "test"})
        assert entry.from_ == 1.5
        data = entry.model_dump(by_alias=True)
        assert "from" in data
        assert data["from"] == 1.5
        assert "from_" not in data

    def test_deserialize_from_json(self):
        data = {"from": 2.0, "to": 6.0, "content": "hello"}
        entry = SubtitleEntry(**data)
        assert entry.from_ == 2.0
        assert entry.content == "hello"


class TestTranscribeResponse:
    """Test TranscribeResponse model."""

    def test_sync_response(self):
        resp = TranscribeResponse(
            task_id="test_001",
            status="completed",
            mode="sync",
            usage=UsageInfo(source="subtitle", model="", duration_seconds=0.5),
        )
        assert resp.status == TaskStatus.completed
        assert resp.mode == "sync"

    def test_async_response(self):
        resp = TranscribeResponse(
            task_id="test_002",
            status="pending",
            mode="async",
            links={"self": "/api/v1/transcribe/test_002"},
        )
        assert resp.status == TaskStatus.pending
        assert resp.links == {"self": "/api/v1/transcribe/test_002"}


class TestTaskStatusResponse:
    """Test TaskStatusResponse model."""

    def test_processing(self):
        resp = TaskStatusResponse(
            task_id="test_001",
            status="processing",
            progress=TaskProgress(phase="downloading_audio", percent=50, message="下载中"),
        )
        assert resp.status == TaskStatus.processing
        assert resp.progress.phase == ProgressPhase.downloading_audio
        assert resp.progress.percent == 50

    def test_completed_with_result(self, sample_completed_result, sample_usage):
        """Uses fixtures from conftest.py."""
        resp = TaskStatusResponse(
            task_id="test_001",
            status="completed",
            progress=TaskProgress(phase="completed", percent=100, message="完成"),
            result=TranscriptResult(**sample_completed_result),
            usage=UsageInfo(**sample_usage),
        )
        assert resp.status == TaskStatus.completed
        assert resp.result is not None
        assert resp.result.entries == 3

    def test_failed(self):
        resp = TaskStatusResponse(
            task_id="test_001",
            status="failed",
            progress=TaskProgress(phase="failed", percent=0, message="音频下载失败"),
        )
        assert resp.status == TaskStatus.failed


class TestHealthResponse:
    """Test HealthResponse model."""

    def test_ok(self):
        resp = HealthResponse(
            status="ok",
            queue={"pending": 0, "running": 0, "completed": 5, "failed": 0},
        )
        assert resp.status == "ok"
        assert resp.queue["completed"] == 5

    def test_default_models(self):
        resp = HealthResponse(status="ok", queue={})
        assert "tiny" in resp.whisper_models
        assert resp.default_model == "small"


class TestVideoInfoResponse:
    """Test VideoInfoResponse model."""

    def test_minimal(self):
        info = VideoInfoResponse(bvid="BV1xxx", title="Test")
        assert info.bvid == "BV1xxx"
        assert info.total_pages == 1
        assert info.author == ""

    def test_with_pages(self):
        from api.models import PageInfo
        info = VideoInfoResponse(
            bvid="BV1xxx",
            title="Test",
            pages=[PageInfo(page=1, part="P1", cid=100), PageInfo(page=2, part="P2", cid=200)],
            total_pages=2,
            has_subtitle=True,
            subtitle_languages=["zh-Hans"],
        )
        assert info.total_pages == 2
        assert len(info.pages) == 2
        assert info.has_subtitle is True
        assert "zh-Hans" in info.subtitle_languages


class TestErrorResponse:
    """Test ErrorResponse model."""

    def test_minimal(self):
        err = ErrorResponse(error="invalid_url", message="无法解析 URL")
        assert err.error == "invalid_url"
        assert err.details is None

    def test_with_details(self):
        err = ErrorResponse(error="validation_error", message="参数错误", details={"field": "url"})
        assert err.details == {"field": "url"}


class TestTaskListResponse:
    """Test TaskListResponse model."""

    def test_empty(self):
        resp = TaskListResponse(total=0, limit=20, offset=0, tasks=[])
        assert resp.total == 0
        assert len(resp.tasks) == 0

    def test_with_tasks(self):
        from api.models import TaskSummary
        task = TaskSummary(
            task_id="test_001",
            status="completed",
            mode="sync",
            url="BV1xxx",
            progress=TaskProgress(phase="completed", percent=100, message="完成"),
        )
        resp = TaskListResponse(total=1, limit=20, offset=0, tasks=[task])
        assert resp.total == 1
        assert resp.tasks[0].task_id == "test_001"


class TestSubModels:
    """Test smaller sub-models."""

    def test_usage_info(self):
        usage = UsageInfo(source="whisper", model="small", duration_seconds=930.5)
        assert usage.source == TranscriptSource.whisper
        assert usage.real_time_factor is None

    def test_usage_info_with_rtf(self):
        usage = UsageInfo(source="whisper", model="small", duration_seconds=930.5,
                          audio_duration=3600, real_time_factor=0.26)
        assert usage.real_time_factor == 0.26

    def test_audio_info(self):
        audio = AudioInfo(size_bytes=6291456, duration_seconds=1530)
        assert audio.size_bytes == 6291456

    def test_progress_info(self):
        prog = ProgressInfo(phase="downloading_audio", percent=50, message="下载中",
                            bytes_downloaded=1000, bytes_total=2000)
        assert prog.bytes_downloaded == 1000
        assert prog.percent == 50


class TestSerialization:
    """Test JSON serialization round-trips."""

    def test_transcribe_request_json(self):
        req = TranscribeRequest(url="BV1Gm421W75K", mode="whisper", model="tiny")
        data = req.model_dump(mode="json")
        json_str = json.dumps(data, ensure_ascii=False)
        loaded = json.loads(json_str)
        req2 = TranscribeRequest(**loaded)
        assert req2.url == req.url
        assert req2.mode == req.mode

    def test_health_response_json(self):
        resp = HealthResponse(status="ok", queue={"pending": 1})
        data = resp.model_dump(mode="json")
        json_str = json.dumps(data, ensure_ascii=False)
        loaded = json.loads(json_str)
        assert loaded["status"] == "ok"
        assert loaded["queue"]["pending"] == 1