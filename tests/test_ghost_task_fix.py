"""测试：幽灵任务 bug 修复验证。

验证 queue.complete() 和 queue.fail() 的状态守卫。
"""

import tempfile

import pytest

from bili_scribe.web.models import (
    OutputFormat,
    TaskStatus,
    TranscriptMode,
    WhisperModel,
)
from bili_scribe.web.queue import Task, TaskQueue
from bili_scribe.web.storage import TaskStorage


def _make_task(task_id: str = "test_001", url: str = "BV1234567890") -> Task:
    return Task(
        task_id=task_id,
        url=url,
        mode=TranscriptMode.auto,
        model=WhisperModel.small,
        language="zh",
        page=0,
        output_format=OutputFormat.text,
    )


class TestGhostTaskFix:
    """验证幽灵任务 bug 修复。"""

    def test_complete_requires_processing_status(self):
        """验证: complete() 只能对 processing 状态的任务调用。"""
        queue = TaskQueue()
        task = _make_task("guard_test_001")
        queue.enqueue(task)

        # 任务状态是 pending，complete 应该失败
        result = {"bvid": "BV1234567890", "title": "test"}
        usage = {"source": "whisper", "model": "small", "duration_seconds": 1.0}
        success = queue.complete(task.task_id, result, usage)

        assert success is False, "complete() 应该拒绝 pending 状态的任务"
        completed = queue.peek(task.task_id)
        assert completed is not None
        assert completed.status == TaskStatus.pending  # 状态未改变
        assert completed.started_at is None  # started_at 未设置

    def test_complete_works_for_processing_status(self):
        """验证: complete() 可以对 processing 状态的任务调用。"""
        queue = TaskQueue()
        task = _make_task("guard_test_002")
        queue.enqueue(task)

        # dequeue 设置状态为 processing
        dequeued = queue.dequeue()
        assert dequeued is not None
        assert dequeued.status == TaskStatus.processing
        assert dequeued.started_at is not None

        # complete 应该成功
        result = {"bvid": "BV1234567890", "title": "test"}
        usage = {"source": "whisper", "model": "small", "duration_seconds": 1.0}
        success = queue.complete(dequeued.task_id, result, usage)

        assert success is True
        completed = queue.peek(dequeued.task_id)
        assert completed is not None
        assert completed.status == TaskStatus.completed
        assert completed.started_at is not None
        assert completed.result is not None

    def test_fail_requires_processing_status(self):
        """验证: fail() 只能对 processing 状态的任务调用。"""
        queue = TaskQueue()
        task = _make_task("guard_test_003")
        queue.enqueue(task)

        # 任务状态是 pending，fail 应该失败
        success = queue.fail(task.task_id, "test error")

        assert success is False, "fail() 应该拒绝 pending 状态的任务"
        failed = queue.peek(task.task_id)
        assert failed is not None
        assert failed.status == TaskStatus.pending  # 状态未改变

    def test_fail_works_for_processing_status(self):
        """验证: fail() 可以对 processing 状态的任务调用。"""
        queue = TaskQueue()
        task = _make_task("guard_test_004")
        queue.enqueue(task)

        # dequeue 设置状态为 processing
        dequeued = queue.dequeue()
        assert dequeued is not None

        # fail 应该成功
        success = queue.fail(dequeued.task_id, "test error")

        assert success is True
        failed = queue.peek(dequeued.task_id)
        assert failed is not None
        assert failed.status == TaskStatus.failed
        assert failed.error == "test error"

    def test_正常流程不受影响(self):
        """验证: 正常的 enqueue → dequeue → complete 流程不受影响。"""
        queue = TaskQueue()
        task = _make_task("normal_flow_001")
        queue.enqueue(task)

        # 正常流程
        dequeued = queue.dequeue()
        assert dequeued is not None
        assert dequeued.started_at is not None

        result = {"bvid": "BV1234567890", "title": "test"}
        usage = {"source": "whisper", "model": "small", "duration_seconds": 1.0}
        success = queue.complete(dequeued.task_id, result, usage)

        assert success is True
        completed = queue.peek(dequeued.task_id)
        assert completed is not None
        assert completed.status == TaskStatus.completed
        assert completed.started_at is not None
        assert completed.result is not None

    def test_磁盘持久化_修复后(self):
        """验证: 修复后，磁盘持久化保持正确的任务状态。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = TaskStorage(tmpdir)
            queue = TaskQueue()

            task = _make_task("disk_fix_001")
            queue.enqueue(task)

            # 正常流程
            dequeued = queue.dequeue()
            assert dequeued is not None

            result = {"bvid": "BV1234567890", "title": "test"}
            usage = {"source": "whisper", "model": "small", "duration_seconds": 1.0}
            queue.complete(dequeued.task_id, result, usage)

            completed = queue.peek(dequeued.task_id)
            assert completed is not None
            storage.save(completed)

            # 从磁盘恢复
            queue2 = TaskQueue()
            recovered = storage.recover(queue2)

            assert recovered == 1
            loaded = queue2.peek(dequeued.task_id)
            assert loaded is not None
            assert loaded.status == TaskStatus.completed
            assert loaded.started_at is not None
            assert loaded.result is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
