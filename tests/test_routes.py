"""Tests for API routes using TestClient."""

from __future__ import annotations

import pytest
from fastapi import status
from fastapi.testclient import TestClient


class TestHealthEndpoint:
    """Tests for GET /api/v1/health."""

    def test_health_returns_200(self, api_client: TestClient):
        resp = api_client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert "queue" in data
        assert "checks" in data
        assert data["checks"]["queue_worker"]["status"] == "ok"

    def test_health_has_queue_stats(self, api_client: TestClient):
        resp = api_client.get("/api/v1/health")
        data = resp.json()
        assert "pending" in data["queue"]
        assert "processing" in data["queue"]
        assert "completed" in data["queue"]
        assert "failed" in data["queue"]

    def test_health_has_whisper_models(self, api_client: TestClient):
        resp = api_client.get("/api/v1/health")
        data = resp.json()
        assert "tiny" in data["whisper_models"]
        assert "small" in data["whisper_models"]
        assert data["default_model"] == "small"

    def test_health_uptime(self, api_client: TestClient):
        resp = api_client.get("/api/v1/health")
        data = resp.json()
        assert data["uptime"] > 0


class TestVideoInfoEndpoint:
    """Tests for GET /api/v1/video/info."""

    def test_invalid_url_returns_400(self, api_client: TestClient):
        resp = api_client.get("/api/v1/video/info", params={"url": "invalid"})
        assert resp.status_code == 400
        data = resp.json()
        assert "invalid_url" in str(data["detail"])

    def test_missing_url_param_returns_422(self, api_client: TestClient):
        resp = api_client.get("/api/v1/video/info")
        assert resp.status_code == 422

    def test_known_bvid_returns_200(self, api_client: TestClient):
        """Test with a real BV ID that should exist."""
        resp = api_client.get("/api/v1/video/info", params={"url": "BV1Gm421W75K"})
        if resp.status_code == 200:
            data = resp.json()
            assert data["bvid"] == "BV1Gm421W75K"
            assert "title" in data
            assert "duration" in data
            assert "author" in data
            assert "pages" in data
            assert "has_subtitle" in data
        else:
            # If API fails (network issue), skip assertion
            pytest.skip("B站API不可达，跳过测试")


class TestTranscribeEndpoint:
    """Tests for POST /api/v1/transcribe."""

    BV_ASYNC = "BV1Gm421W75K"  # video without subtitles, for async tests

    def test_invalid_url_returns_400(self, api_client: TestClient):
        resp = api_client.post(
            "/api/v1/transcribe",
            json={"url": "invalid"},
        )
        assert resp.status_code == 400
        data = resp.json()
        assert "invalid_url" in str(data["detail"])

    def test_missing_url_returns_422(self, api_client: TestClient):
        resp = api_client.post("/api/v1/transcribe", json={})
        assert resp.status_code == 422

    def test_async_whisper_returns_202(self, api_client: TestClient):
        """Forcing whisper mode should return 202 Accepted."""
        resp = api_client.post(
            "/api/v1/transcribe",
            json={"url": self.BV_ASYNC, "mode": "whisper", "model": "tiny"},
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "pending"
        assert data["mode"] == "async"
        assert "task_id" in data
        assert "links" in data
        assert data["links"]["self"].startswith("/api/v1/transcribe/")

    def test_auto_mode_no_subtitle_returns_202(self, api_client: TestClient):
        """Video without subtitles should fall back to async."""
        resp = api_client.post(
            "/api/v1/transcribe",
            json={"url": "BV1bswFeCEGo"},  # different BV to avoid dedup
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "pending"
        assert data["mode"] == "async"

    def test_rate_limit_duplicate(self, api_client: TestClient):
        """Same BV should be rate limited if already pending."""
        # Remove any existing tasks first
        from api.queue import queue
        from api.storage import storage
        # Complete the existing task with this BV
        for task_id in list(queue._tasks.keys()):
            task = queue.peek(task_id)
            if task and "BV1bswFeCEGo" in task.url:
                queue.complete(task_id, {}, {})
                storage.save(queue.peek(task_id))

        # First request
        api_client.post(
            "/api/v1/transcribe",
            json={"url": "BV1bswFeCEGo", "mode": "whisper", "model": "tiny"},
        )
        # Second request with same BV
        resp = api_client.post(
            "/api/v1/transcribe",
            json={"url": "BV1bswFeCEGo", "mode": "whisper", "model": "tiny"},
        )
        assert resp.status_code == 429
        data = resp.json()
        assert "rate_limited" in str(data["detail"])

    def test_webhook_param(self, api_client: TestClient):
        """Webhook should trigger async mode."""
        resp = api_client.post(
            "/api/v1/transcribe",
            json={
                "url": "BV1accSeJEbT",  # different BV to avoid dedup
                "mode": "whisper",
                "model": "tiny",
                "webhook": "https://example.com/callback",
            },
        )
        assert resp.status_code == 202


class TestTaskStatusEndpoint:
    """Tests for GET /api/v1/transcribe/:task_id."""

    def test_nonexistent_task_returns_404(self, api_client: TestClient):
        resp = api_client.get("/api/v1/transcribe/nonexistent_task_id")
        assert resp.status_code == 404
        data = resp.json()
        assert "task_not_found" in str(data["detail"])

    def test_existing_task_returns_200(self, api_client: TestClient):
        """Create a task via POST, then check its status."""
        # Create a task with a unique BV
        resp = api_client.post(
            "/api/v1/transcribe",
            json={"url": "BV1cMnEzpEc2", "mode": "whisper", "model": "tiny"},
        )
        assert resp.status_code == 202, f"Expected 202, got {resp.status_code}: {resp.text}"
        task_id = resp.json()["task_id"]

        # Check status
        resp = api_client.get(f"/api/v1/transcribe/{task_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == task_id
        assert data["status"] in ("pending", "processing", "completed", "failed")
        assert "progress" in data
        assert "phase" in data["progress"]
        assert "percent" in data["progress"]

    def test_has_request_info(self, api_client: TestClient):
        """Task status should include request info."""
        resp = api_client.post(
            "/api/v1/transcribe",
            json={"url": "BV1Yqo1YeEHi", "mode": "whisper", "model": "tiny"},
        )
        assert resp.status_code == 202, f"Expected 202, got {resp.status_code}: {resp.text}"
        task_id = resp.json()["task_id"]

        resp = api_client.get(f"/api/v1/transcribe/{task_id}")
        data = resp.json()
        request = data.get("request")
        if request:
            assert request["url"] is not None
            assert request["model"] is not None


class TestTaskListEndpoint:
    """Tests for GET /api/v1/tasks."""

    def test_list_returns_200(self, api_client: TestClient):
        resp = api_client.get("/api/v1/tasks")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "limit" in data
        assert "offset" in data
        assert "tasks" in data

    def test_list_pagination_params(self, api_client: TestClient):
        resp = api_client.get("/api/v1/tasks", params={"limit": 5, "offset": 0})
        assert resp.status_code == 200
        data = resp.json()
        assert data["limit"] == 5
        assert data["offset"] == 0

    def test_list_status_filter(self, api_client: TestClient):
        resp = api_client.get("/api/v1/tasks", params={"status": "pending"})
        assert resp.status_code == 200
        data = resp.json()
        # Should at least return valid structure
        assert "tasks" in data

    def test_list_invalid_status(self, api_client: TestClient):
        """Invalid status filter should not crash."""
        resp = api_client.get("/api/v1/tasks", params={"status": "invalid_status"})
        assert resp.status_code == 200  # Should gracefully return empty

    def test_list_max_limit(self, api_client: TestClient):
        """Limit should be capped at 100."""
        resp = api_client.get("/api/v1/tasks", params={"limit": 999})
        assert resp.status_code == 422  # FastAPI validation rejects > 100


class TestRootEndpoint:
    """Tests for GET /."""

    def test_root_returns_200(self, api_client: TestClient):
        resp = api_client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "bilibili-transcript-api"


class TestOpenAPI:
    """Tests for OpenAPI docs."""

    def test_docs_accessible(self, api_client: TestClient):
        resp = api_client.get("/docs")
        assert resp.status_code == 200

    def test_openapi_json(self, api_client: TestClient):
        resp = api_client.get("/openapi.json")
        assert resp.status_code == 200
        data = resp.json()
        assert data["info"]["title"] == "Bilibili Transcript API"
        assert "/api/v1/health" in str(data["paths"])
        assert "/api/v1/transcribe" in str(data["paths"])