"""Pytest configuration and shared fixtures for API tests."""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

# Ensure the project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Fixtures ──


@pytest.fixture
def api_client() -> Generator[TestClient, None, None]:
    """Create a TestClient bound to the FastAPI application.

    Yields:
        A TestClient instance for making HTTP requests to the API.
    """
    from src.web.server import app

    with TestClient(app) as client:
        yield client


@pytest.fixture
def temp_storage_dir() -> Generator[str, None, None]:
    """Create a temporary directory for task storage files.

    The directory is automatically cleaned up after the test.

    Yields:
        Path to the temporary directory.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def fresh_queue():
    """Create a fresh empty TaskQueue with a small max size.

    Returns:
        A TaskQueue instance with max_size=10.
    """
    from src.web.queue import TaskQueue

    return TaskQueue(max_size=10)


@pytest.fixture
def sample_task():
    """Create a sample task with default values for testing.

    Returns:
        A Task instance with known test values.
    """
    from src.web.models import OutputFormat, TranscriptMode, WhisperModel
    from src.web.queue import Task

    return Task(
        task_id="test_001",
        url="BV1Gm421W75K",
        mode=TranscriptMode.auto,
        model=WhisperModel.small,
        language="zh",
        page=0,
        output_format=OutputFormat.text,
    )


@pytest.fixture
def sample_completed_result() -> dict:
    """Create a sample completed transcription result.

    Returns:
        A dictionary mimicking a completed transcription result.
    """
    return {
        "bvid": "BV1Gm421W75K",
        "title": "测试视频标题",
        "author": "测试作者",
        "duration": 3600,
        "source": "subtitle",
        "total_pages": 1,
        "current_page": 0,
        "entries": 3,
        "subtitles": [
            {"from": 0.0, "to": 3.5, "content": "大家好"},
            {"from": 3.5, "to": 8.2, "content": "欢迎来到测试"},
            {"from": 8.2, "to": 12.0, "content": "今天我们讲测试"},
        ],
        "full_text": "大家好\n欢迎来到测试\n今天我们讲测试",
    }


@pytest.fixture
def sample_usage() -> dict:
    """Create sample usage statistics.

    Returns:
        A dictionary with usage data.
    """
    return {
        "source": "subtitle",
        "model": "",
        "duration_seconds": 0.5,
    }
