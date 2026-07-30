"""In-memory task queue with thread-safe operations."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from src.web.models import (
    OutputFormat,
    ProgressInfo,
    ProgressPhase,
    TaskStatus,
    TranscriptMode,
    WhisperModel,
)


# Default task timeout: 6 hours
DEFAULT_TASK_TIMEOUT = 6 * 3600
# Max pending tasks in queue
MAX_QUEUE_SIZE = 100


@dataclass
class Task:
    """Represents a single transcription task."""

    task_id: str
    url: str
    mode: TranscriptMode
    model: WhisperModel
    language: str = "zh"
    page: int = 0
    output_format: OutputFormat = OutputFormat.text
    cookie: str = ""
    webhook: str = ""

    status: TaskStatus = TaskStatus.pending
    progress: ProgressInfo = field(default_factory=lambda: ProgressInfo(
        phase=ProgressPhase.queued, percent=0, message="等待处理"
    ))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[dict] = None
    usage: Optional[dict] = None
    error: Optional[str] = None

    def elapsed_seconds(self) -> float:
        """Calculate the time elapsed since the task was created.

        Returns:
            Number of seconds since creation.
        """
        return (datetime.now(timezone.utc) - self.created_at).total_seconds()

    def is_stale(self, timeout: int = DEFAULT_TASK_TIMEOUT) -> bool:
        """Check if a running task has exceeded the allowed timeout.

        Args:
            timeout: Maximum allowed runtime in seconds before considering
                the task stale. Defaults to DEFAULT_TASK_TIMEOUT (6 hours).

        Returns:
            True if the task is in processing state and has exceeded the timeout.
        """
        if self.status != TaskStatus.processing or self.started_at is None:
            return False
        elapsed = (datetime.now(timezone.utc) - self.started_at).total_seconds()
        return elapsed > timeout


class TaskQueue:
    """Thread-safe in-memory task queue."""

    def __init__(self, max_size: int = MAX_QUEUE_SIZE):
        self._lock = threading.Lock()
        self._max_size = max_size
        # OrderedDict maintains insertion order for FIFO
        self._tasks: OrderedDict[str, Task] = OrderedDict()

    # ── Core operations ──

    def enqueue(self, task: Task) -> bool:
        """Add a task to the queue.

        Rejects the task if the queue is full or if a task with the
        same BV ID is already pending or processing.

        Args:
            task: The Task instance to enqueue.

        Returns:
            True if the task was added, False if rejected.
        """
        with self._lock:
            if len(self._tasks) >= self._max_size:
                return False

            # Deduplication: same BV only one pending/processing allowed
            bvid = self._extract_bvid(task.url)
            if bvid:
                for t in self._tasks.values():
                    if t.status in (TaskStatus.pending, TaskStatus.processing):
                        if self._extract_bvid(t.url) == bvid:
                            return False

            self._tasks[task.task_id] = task
            return True

    def dequeue(self) -> Optional[Task]:
        """Retrieve the next pending task in FIFO order and mark it as processing.

        Returns:
            The next pending Task, or None if the queue is empty.
        """
        with self._lock:
            for task_id, task in list(self._tasks.items()):
                if task.status == TaskStatus.pending:
                    task.status = TaskStatus.processing
                    task.started_at = datetime.now(timezone.utc)
                    task.progress = ProgressInfo(
                        phase=ProgressPhase.fetching_info,
                        percent=5,
                        message="正在获取视频信息",
                    )
                    return task
            return None

    def peek(self, task_id: str) -> Optional[Task]:
        """Get a task by ID without modifying its state.

        Args:
            task_id: The unique identifier of the task.

        Returns:
            The Task if found, or None.
        """
        with self._lock:
            return self._tasks.get(task_id)

    def complete(self, task_id: str, result: dict, usage: dict) -> bool:
        """Mark a task as completed with its result and usage data.

        Args:
            task_id: The unique identifier of the task.
            result: The transcription result dictionary.
            usage: The usage statistics dictionary.

        Returns:
            True if the task was found and updated, False otherwise.
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            task.status = TaskStatus.completed
            task.completed_at = datetime.now(timezone.utc)
            task.result = result
            task.usage = usage
            task.progress = ProgressInfo(
                phase=ProgressPhase.completed, percent=100, message="转录完成"
            )
            return True

    def fail(self, task_id: str, error: str) -> bool:
        """Mark a task as failed with an error message.

        Args:
            task_id: The unique identifier of the task.
            error: A human-readable error description.

        Returns:
            True if the task was found and updated, False otherwise.
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            task.status = TaskStatus.failed
            task.completed_at = datetime.now(timezone.utc)
            task.error = error
            task.progress = ProgressInfo(
                phase=ProgressPhase.failed, percent=0, message=error
            )
            return True

    def update_progress(self, task_id: str, phase: ProgressPhase, percent: int, message: str,
                        bytes_downloaded: int | None = None,
                        bytes_total: int | None = None) -> bool:
        """Update the progress information for a running task.

        Args:
            task_id: The unique identifier of the task.
            phase: The current progress phase.
            percent: Progress percentage (0-100).
            message: A human-readable progress message.
            bytes_downloaded: Optional bytes downloaded so far.
            bytes_total: Optional total bytes to download.

        Returns:
            True if the task was found and updated, False otherwise.
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            task.progress = ProgressInfo(
                phase=phase, percent=percent, message=message,
                bytes_downloaded=bytes_downloaded, bytes_total=bytes_total,
            )
            return True

    # ── Query operations ──

    def list(self, status: str | None = None,
             limit: int = 20, offset: int = 0) -> tuple[list[Task], int]:
        """List tasks with optional status filter and pagination.

        Args:
            status: Optional status filter ('pending', 'processing',
                'completed', 'failed'). Returns all statuses if None.
            limit: Maximum number of tasks to return (default 20).
            offset: Number of tasks to skip for pagination.

        Returns:
            A tuple of (list of Tasks, total count matching the filter).
        """
        with self._lock:
            all_tasks = list(self._tasks.values())

            if status:
                all_tasks = [t for t in all_tasks if t.status.value == status]

            # Sort by created_at descending
            all_tasks.sort(key=lambda t: t.created_at, reverse=True)

            total = len(all_tasks)
            paginated = all_tasks[offset:offset + limit]
            return paginated, total

    def stats(self) -> dict[str, int]:
        """Get queue statistics by status.

        Returns:
            A dictionary with keys 'pending', 'processing', 'completed',
            'failed' and their respective counts.
        """
        with self._lock:
            counts = {"pending": 0, "processing": 0, "completed": 0, "failed": 0}
            for task in self._tasks.values():
                status = task.status.value
                if status in counts:
                    counts[status] += 1
            return counts

    def remove(self, task_id: str) -> bool:
        """Remove a task from the queue by its ID.

        Args:
            task_id: The unique identifier of the task to remove.

        Returns:
            True if the task was found and removed, False otherwise.
        """
        with self._lock:
            if task_id in self._tasks:
                del self._tasks[task_id]
                return True
            return False

    # ── Maintenance ──

    def detect_stale_tasks(self, timeout: int = DEFAULT_TASK_TIMEOUT) -> list[Task]:
        """Find and return all processing tasks that have exceeded the timeout.

        Args:
            timeout: Maximum allowed runtime in seconds.

        Returns:
            A list of stale Task instances.
        """
        stale = []
        with self._lock:
            for task in self._tasks.values():
                if task.is_stale(timeout):
                    stale.append(task)
        return stale

    def size(self) -> int:
        """Get the total number of tasks currently in the queue.

        Returns:
            The number of tasks (across all statuses).
        """
        with self._lock:
            return len(self._tasks)

    # ── Helpers ──

    @staticmethod
    def _extract_bvid(url: str) -> str | None:
        """Extract the BV ID from a Bilibili URL or bare ID string.

        Args:
            url: A Bilibili URL or BV ID string.

        Returns:
            The 12-character BV ID if found, or None.
        """
        import re
        m = re.search(r"(BV[\w]{10})", url)
        return m.group(1) if m else None


# Global singleton
queue = TaskQueue()