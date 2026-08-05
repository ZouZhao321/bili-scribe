"""Task persistence storage — saves/restores task state to disk."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from api.models import (
    OutputFormat,
    ProgressInfo,
    ProgressPhase,
    TaskStatus,
    TranscriptMode,
    WhisperModel,
)
from api.queue import Task, TaskQueue


# Default storage directory
DEFAULT_STORAGE_DIR = os.path.expanduser("~/.bilibili-api/tasks")


def _serialize_task(task: Task) -> dict:
    """Serialize a Task to a JSON-serializable dict."""
    return {
        "task_id": task.task_id,
        "url": task.url,
        "mode": task.mode.value if isinstance(task.mode, TranscriptMode) else task.mode,
        "model": task.model.value if isinstance(task.model, WhisperModel) else task.model,
        "language": task.language,
        "page": task.page,
        "output_format": task.output_format.value if isinstance(task.output_format, OutputFormat) else task.output_format,
        "cookie": task.cookie,
        "webhook": task.webhook,
        "status": task.status.value if isinstance(task.status, TaskStatus) else task.status,
        "progress": {
            "phase": task.progress.phase.value if isinstance(task.progress.phase, ProgressPhase) else task.progress.phase,
            "percent": task.progress.percent,
            "message": task.progress.message,
            "bytes_downloaded": task.progress.bytes_downloaded,
            "bytes_total": task.progress.bytes_total,
        },
        "created_at": task.created_at.isoformat() if isinstance(task.created_at, datetime) else task.created_at,
        "started_at": task.started_at.isoformat() if isinstance(task.started_at, datetime) else task.started_at,
        "completed_at": task.completed_at.isoformat() if isinstance(task.completed_at, datetime) else task.completed_at,
        "result": task.result,
        "usage": task.usage,
        "error": task.error,
    }


def _deserialize_task(data: dict) -> Task:
    """Deserialize a dict back to a Task."""
    progress_data = data.get("progress", {})
    progress = ProgressInfo(
        phase=progress_data.get("phase", "queued"),
        percent=progress_data.get("percent", 0),
        message=progress_data.get("message", ""),
        bytes_downloaded=progress_data.get("bytes_downloaded"),
        bytes_total=progress_data.get("bytes_total"),
    )

    def _parse_dt(val):
        if isinstance(val, datetime):
            return val
        if isinstance(val, str):
            try:
                return datetime.fromisoformat(val)
            except (ValueError, TypeError):
                return None
        return None

    return Task(
        task_id=data["task_id"],
        url=data["url"],
        mode=data.get("mode", "auto"),
        model=data.get("model", "small"),
        language=data.get("language", "zh"),
        page=data.get("page", 0),
        output_format=data.get("output_format", "text"),
        cookie=data.get("cookie", ""),
        webhook=data.get("webhook", ""),
        status=data.get("status", "pending"),
        progress=progress,
        created_at=_parse_dt(data.get("created_at")) or datetime.utcnow(),
        started_at=_parse_dt(data.get("started_at")),
        completed_at=_parse_dt(data.get("completed_at")),
        result=data.get("result"),
        usage=data.get("usage"),
        error=data.get("error"),
    )


class TaskStorage:
    """Persists task state to JSON files on disk.

    Each task is stored as a separate JSON file: <storage_dir>/<task_id>.json
    On startup, all files are loaded and recovered into the queue.
    """

    def __init__(self, storage_dir: str = DEFAULT_STORAGE_DIR):
        self._dir = storage_dir
        self._lock = threading.Lock()

    @property
    def dir(self) -> str:
        return self._dir

    def ensure_dir(self) -> None:
        """Create the storage directory if it doesn't exist."""
        Path(self._dir).mkdir(parents=True, exist_ok=True)

    def save(self, task: Task) -> None:
        """Save a single task to disk."""
        self.ensure_dir()
        filepath = os.path.join(self._dir, f"{task.task_id}.json")
        data = _serialize_task(task)
        with self._lock:
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except OSError as e:
                print(f"[storage] Failed to save task {task.task_id}: {e}", file=__import__('sys').stderr)

    def load(self, task_id: str) -> Optional[Task]:
        """Load a single task from disk by ID."""
        filepath = os.path.join(self._dir, f"{task_id}.json")
        if not os.path.exists(filepath):
            return None
        with self._lock:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return _deserialize_task(data)
            except (json.JSONDecodeError, KeyError):
                return None

    def delete(self, task_id: str) -> bool:
        """Delete a task file from disk."""
        filepath = os.path.join(self._dir, f"{task_id}.json")
        try:
            if os.path.exists(filepath):
                with self._lock:
                    os.remove(filepath)
                return True
        except OSError as e:
            print(f"[storage] Failed to delete task {task_id}: {e}", file=__import__('sys').stderr)
        return False

    def recover(self, queue: TaskQueue) -> int:
        """Load all saved tasks from disk and restore them into the queue.

        Completed/failed tasks are loaded for querying.
        Pending tasks are re-queued.
        Processing tasks are reset to pending (safe recovery).
        Returns the number of tasks recovered.
        """
        self.ensure_dir()
        recovered = 0
        try:
            filenames = os.listdir(self._dir)
        except OSError as e:
            print(f"[storage] Failed to list storage dir: {e}", file=__import__('sys').stderr)
            return 0

        for filename in filenames:
            if not filename.endswith(".json"):
                continue
            task_id = filename[:-5]  # remove .json
            task = self.load(task_id)
            if task is None:
                continue

            # Reset processing tasks to pending for safe recovery
            if task.status == TaskStatus.processing:
                task.status = TaskStatus.pending
                task.started_at = None
                task.progress = ProgressInfo(
                    phase=ProgressPhase.queued, percent=0, message="等待处理（重启恢复）"
                )

            # Re-add to queue (overwrite if exists)
            q = queue
            existing = q.peek(task_id)
            if existing is None:
                q.enqueue(task)
            else:
                # Update existing task in place (simplified)
                pass

            recovered += 1

        return recovered

    def list_files(self) -> list[str]:
        """List all task IDs on disk."""
        self.ensure_dir()
        tasks = []
        try:
            filenames = sorted(os.listdir(self._dir))
        except OSError as e:
            print(f"[storage] Failed to list storage dir: {e}", file=__import__('sys').stderr)
            return tasks
        for filename in filenames:
            if filename.endswith(".json"):
                tasks.append(filename[:-5])
        return tasks


# Global singleton
storage = TaskStorage()