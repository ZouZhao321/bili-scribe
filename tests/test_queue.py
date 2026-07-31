"""Tests for in-memory task queue (api/queue.py)."""

from __future__ import annotations

from src.web.models import ProgressPhase, TaskStatus, TranscriptMode, WhisperModel
from src.web.queue import Task, TaskQueue


class TestTask:
    """Test Task dataclass."""

    def test_default_values(self, sample_task):
        """Default values."""
        assert sample_task.status == TaskStatus.pending
        assert sample_task.progress.phase == ProgressPhase.queued
        assert sample_task.progress.percent == 0
        assert sample_task.created_at is not None
        assert sample_task.started_at is None
        assert sample_task.completed_at is None
        assert sample_task.result is None
        assert sample_task.error is None

    def test_is_stale(self, sample_task):
        """Is stale."""
        assert sample_task.is_stale() is False  # not processing

        sample_task.status = TaskStatus.processing
        sample_task.started_at = None
        assert sample_task.is_stale() is False  # not started

        # Force stale with 0 timeout
        from datetime import datetime, timedelta, timezone

        sample_task.started_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        assert sample_task.is_stale(timeout=0) is True  # should be stale

    def test_elapsed_seconds(self, sample_task):
        """Elapsed seconds."""
        elapsed = sample_task.elapsed_seconds()
        assert elapsed >= 0


class TestTaskQueue:
    """Test TaskQueue operations."""

    def test_enqueue_dequeue(self, fresh_queue, sample_task):
        """Enqueue dequeue."""
        assert fresh_queue.enqueue(sample_task) is True
        assert fresh_queue.size() == 1

        task = fresh_queue.dequeue()
        assert task is not None
        assert task.task_id == "test_001"
        assert task.status == TaskStatus.processing
        assert task.started_at is not None

        # Second dequeue should return None
        assert fresh_queue.dequeue() is None

    def test_peek(self, fresh_queue, sample_task):
        """Peek."""
        fresh_queue.enqueue(sample_task)
        task = fresh_queue.peek("test_001")
        assert task is not None
        assert task.task_id == "test_001"

        # Non-existent
        assert fresh_queue.peek("nonexistent") is None

    def test_complete(self, fresh_queue, sample_task):
        """Complete."""
        fresh_queue.enqueue(sample_task)
        fresh_queue.dequeue()  # mark as processing

        result = {"bvid": "BV1xxx", "entries": 5}
        usage = {"source": "subtitle", "duration_seconds": 0.5}
        assert fresh_queue.complete("test_001", result, usage) is True

        task = fresh_queue.peek("test_001")
        assert task.status == TaskStatus.completed
        assert task.result == result
        assert task.completed_at is not None

        # Complete non-existent task
        assert fresh_queue.complete("nonexistent", {}, {}) is False

    def test_fail(self, fresh_queue, sample_task):
        """Fail."""
        fresh_queue.enqueue(sample_task)
        fresh_queue.dequeue()

        assert fresh_queue.fail("test_001", "音频下载失败") is True
        task = fresh_queue.peek("test_001")
        assert task.status == TaskStatus.failed
        assert task.error == "音频下载失败"
        assert task.completed_at is not None

        # Fail non-existent task
        assert fresh_queue.fail("nonexistent", "err") is False

    def test_update_progress(self, fresh_queue, sample_task):
        """Update progress."""
        fresh_queue.enqueue(sample_task)
        fresh_queue.dequeue()

        result = fresh_queue.update_progress("test_001", ProgressPhase.downloading_audio, 50, "下载中")
        assert result is True

        task = fresh_queue.peek("test_001")
        assert task.progress.phase == ProgressPhase.downloading_audio
        assert task.progress.percent == 50
        assert task.progress.message == "下载中"

        # Update non-existent task
        assert fresh_queue.update_progress("nonexistent", ProgressPhase.queued, 0, "") is False

    def test_full_lifecycle(self, fresh_queue, sample_task):
        """Test the full lifecycle: enqueue → dequeue → complete."""
        fresh_queue.enqueue(sample_task)
        fresh_queue.dequeue()
        fresh_queue.complete("test_001", {"bvid": "BV1xxx"}, {"source": "subtitle"})

        task = fresh_queue.peek("test_001")
        assert task.status == TaskStatus.completed
        assert task.result["bvid"] == "BV1xxx"

    def test_stats(self, fresh_queue, sample_task):
        """Stats."""
        assert fresh_queue.stats() == {"pending": 0, "processing": 0, "completed": 0, "failed": 0}

        fresh_queue.enqueue(sample_task)
        assert fresh_queue.stats() == {"pending": 1, "processing": 0, "completed": 0, "failed": 0}

        fresh_queue.dequeue()
        assert fresh_queue.stats() == {"pending": 0, "processing": 1, "completed": 0, "failed": 0}

        fresh_queue.complete("test_001", {}, {})
        assert fresh_queue.stats() == {"pending": 0, "processing": 0, "completed": 1, "failed": 0}

    def test_remove(self, fresh_queue, sample_task):
        """Remove."""
        fresh_queue.enqueue(sample_task)
        assert fresh_queue.remove("test_001") is True
        assert fresh_queue.remove("test_001") is False  # already removed

    def test_max_size(self, sample_task):
        """Max size."""
        q = TaskQueue(max_size=2)
        # Create 3 tasks
        t1 = Task(task_id="t1", url="BV1aaa", mode=TranscriptMode.auto, model=WhisperModel.small)
        t2 = Task(task_id="t2", url="BV1bbb", mode=TranscriptMode.auto, model=WhisperModel.small)
        t3 = Task(task_id="t3", url="BV1ccc", mode=TranscriptMode.auto, model=WhisperModel.small)

        assert q.enqueue(t1) is True
        assert q.enqueue(t2) is True
        assert q.enqueue(t3) is False  # queue full
        assert q.size() == 2

    def test_dedup_same_bvid(self, fresh_queue):
        """Same BV should not be enqueued twice when first is pending."""
        t1 = Task(task_id="t1", url="BV1Gm421W75K", mode=TranscriptMode.auto, model=WhisperModel.small)
        t2 = Task(
            task_id="t2",
            url="https://www.bilibili.com/video/BV1Gm421W75K",
            mode=TranscriptMode.auto,
            model=WhisperModel.small,
        )

        assert fresh_queue.enqueue(t1) is True
        assert fresh_queue.enqueue(t2) is False  # duplicate
        assert fresh_queue.size() == 1

    def test_dedup_allows_completed(self, fresh_queue):
        """Same BV should be allowed after first task completes."""
        t1 = Task(task_id="t1", url="BV1Gm421W75K", mode=TranscriptMode.auto, model=WhisperModel.small)
        assert fresh_queue.enqueue(t1) is True
        fresh_queue.dequeue()
        fresh_queue.complete("t1", {}, {})

        # Now enqueue another with same BV - should work
        t2 = Task(task_id="t2", url="BV1Gm421W75K", mode=TranscriptMode.auto, model=WhisperModel.small)
        assert fresh_queue.enqueue(t2) is True

    def test_list_empty(self, fresh_queue):
        """List empty."""
        tasks, total = fresh_queue.list()
        assert tasks == []
        assert total == 0

    def test_list_with_tasks(self, fresh_queue):
        """List with tasks."""
        t1 = Task(task_id="t1", url="BV1aaa", mode=TranscriptMode.auto, model=WhisperModel.small)
        t2 = Task(task_id="t2", url="BV1bbb", mode=TranscriptMode.auto, model=WhisperModel.small)
        fresh_queue.enqueue(t1)
        fresh_queue.enqueue(t2)

        tasks, total = fresh_queue.list()
        assert total == 2
        assert len(tasks) == 2
        # Should be sorted by created_at descending (t2 first)
        assert tasks[0].task_id == "t2"

    def test_list_with_status_filter(self, fresh_queue):
        """List with status filter."""
        t1 = Task(task_id="t1", url="BV1aaa", mode=TranscriptMode.auto, model=WhisperModel.small)
        t2 = Task(task_id="t2", url="BV1bbb", mode=TranscriptMode.auto, model=WhisperModel.small)
        fresh_queue.enqueue(t1)
        fresh_queue.enqueue(t2)
        fresh_queue.dequeue()  # t1 becomes processing
        fresh_queue.complete("t1", {}, {})

        # Only completed
        tasks, total = fresh_queue.list(status="completed")
        assert total == 1
        assert tasks[0].task_id == "t1"

        # Only pending
        tasks, total = fresh_queue.list(status="pending")
        assert total == 1
        assert tasks[0].task_id == "t2"

    def test_list_pagination(self, fresh_queue):
        """List pagination."""
        for i in range(5):
            t = Task(task_id=f"t{i}", url=f"BV1{i:03d}", mode=TranscriptMode.auto, model=WhisperModel.small)
            fresh_queue.enqueue(t)

        # First page with limit 2
        tasks, total = fresh_queue.list(limit=2, offset=0)
        assert total == 5
        assert len(tasks) == 2
        assert tasks[0].task_id == "t4"  # newest first

        # Second page
        tasks, total = fresh_queue.list(limit=2, offset=2)
        assert len(tasks) == 2
        assert tasks[0].task_id == "t2"

        # Offset beyond total
        tasks, total = fresh_queue.list(limit=10, offset=10)
        assert len(tasks) == 0

    def test_detect_stale_tasks(self, fresh_queue, sample_task):
        """Detect stale tasks."""
        fresh_queue.enqueue(sample_task)
        fresh_queue.dequeue()  # marks as processing with started_at

        # Detects stale with 0 timeout
        stale = fresh_queue.detect_stale_tasks(timeout=0)
        assert len(stale) == 1
        assert stale[0].task_id == "test_001"

        # Non-stale pending tasks should not be detected
        t2 = Task(task_id="t2", url="BV1bbb", mode=TranscriptMode.auto, model=WhisperModel.small)
        fresh_queue.enqueue(t2)
        stale = fresh_queue.detect_stale_tasks(timeout=0)
        assert len(stale) == 1  # still only t1 (t2 is pending, not processing)

    def test_extract_bvid(self):
        """Extract bvid."""
        assert TaskQueue._extract_bvid("BV1Gm421W75K") == "BV1Gm421W75K"
        assert TaskQueue._extract_bvid("https://www.bilibili.com/video/BV1Gm421W75K") == "BV1Gm421W75K"
        assert TaskQueue._extract_bvid("https://b23.tv/xxxxx") is None
        assert TaskQueue._extract_bvid("hello") is None

    def test_fifo_order(self, fresh_queue):
        """Tasks should be dequeued in FIFO order."""
        t1 = Task(task_id="t1", url="BV1aaa", mode=TranscriptMode.auto, model=WhisperModel.small)
        t2 = Task(task_id="t2", url="BV1bbb", mode=TranscriptMode.auto, model=WhisperModel.small)
        t3 = Task(task_id="t3", url="BV1ccc", mode=TranscriptMode.auto, model=WhisperModel.small)

        fresh_queue.enqueue(t1)
        fresh_queue.enqueue(t2)
        fresh_queue.enqueue(t3)

        assert fresh_queue.dequeue().task_id == "t1"
        assert fresh_queue.dequeue().task_id == "t2"
        assert fresh_queue.dequeue().task_id == "t3"
