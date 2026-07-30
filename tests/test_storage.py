"""Tests for task persistence storage (api/storage.py)."""

from __future__ import annotations

import os

import pytest

from api.models import TaskStatus
from api.queue import Task, TaskQueue
from api.storage import TaskStorage


class TestTaskStorage:
    """Test TaskStorage operations."""

    def test_save_and_load(self, temp_storage_dir, sample_task):
        storage = TaskStorage(temp_storage_dir)
        storage.save(sample_task)

        # Check file exists
        filepath = os.path.join(temp_storage_dir, f"{sample_task.task_id}.json")
        assert os.path.exists(filepath)

        # Load back
        loaded = storage.load(sample_task.task_id)
        assert loaded is not None
        assert loaded.task_id == sample_task.task_id
        assert loaded.url == sample_task.url
        assert loaded.status == TaskStatus.pending

    def test_save_and_load_completed(self, temp_storage_dir, sample_task, sample_completed_result, sample_usage):
        storage = TaskStorage(temp_storage_dir)

        # Mark as completed and save
        sample_task.status = TaskStatus.completed
        sample_task.result = sample_completed_result
        sample_task.usage = sample_usage
        storage.save(sample_task)

        loaded = storage.load(sample_task.task_id)
        assert loaded.status == TaskStatus.completed
        assert loaded.result["bvid"] == "BV1Gm421W75K"
        assert loaded.result["entries"] == 3
        assert loaded.usage["source"] == "subtitle"

    def test_save_and_load_failed(self, temp_storage_dir, sample_task):
        storage = TaskStorage(temp_storage_dir)

        sample_task.status = TaskStatus.failed
        sample_task.error = "音频下载失败"
        storage.save(sample_task)

        loaded = storage.load(sample_task.task_id)
        assert loaded.status == TaskStatus.failed
        assert loaded.error == "音频下载失败"

    def test_load_nonexistent(self, temp_storage_dir):
        storage = TaskStorage(temp_storage_dir)
        assert storage.load("nonexistent") is None

    def test_delete(self, temp_storage_dir, sample_task):
        storage = TaskStorage(temp_storage_dir)
        storage.save(sample_task)

        assert storage.delete(sample_task.task_id) is True
        assert storage.load(sample_task.task_id) is None
        assert storage.delete("nonexistent") is False

    def test_list_files(self, temp_storage_dir):
        storage = TaskStorage(temp_storage_dir)

        # Empty directory
        assert storage.list_files() == []

        # Save some tasks
        for i in range(3):
            task = Task(task_id=f"task_{i}", url=f"BV1{i:03d}", mode="auto", model="small")
            storage.save(task)

        files = storage.list_files()
        assert len(files) == 3
        assert "task_0" in files
        assert "task_1" in files
        assert "task_2" in files

    def test_recover_empty(self, temp_storage_dir):
        storage = TaskStorage(temp_storage_dir)
        queue = TaskQueue()
        recovered = storage.recover(queue)
        assert recovered == 0

    def test_recover_pending_tasks(self, temp_storage_dir):
        storage = TaskStorage(temp_storage_dir)
        queue = TaskQueue()

        # Save a pending task
        task = Task(task_id="pending_task", url="BV1xxx", mode="auto", model="small")
        storage.save(task)

        recovered = storage.recover(queue)
        assert recovered == 1

        # Task should be in queue
        t = queue.peek("pending_task")
        assert t is not None
        assert t.status == TaskStatus.pending

    def test_recover_completed_tasks(self, temp_storage_dir):
        storage = TaskStorage(temp_storage_dir)
        queue = TaskQueue()

        # Save a completed task
        task = Task(task_id="done_task", url="BV1xxx", mode="auto", model="small")
        task.status = TaskStatus.completed
        task.result = {"bvid": "BV1xxx"}
        storage.save(task)

        recovered = storage.recover(queue)
        assert recovered == 1

        t = queue.peek("done_task")
        assert t is not None
        assert t.status == TaskStatus.completed

    def test_recover_processing_task_reset_to_pending(self, temp_storage_dir):
        """Processing tasks should be reset to pending on recovery."""
        storage = TaskStorage(temp_storage_dir)
        queue = TaskQueue()

        task = Task(task_id="proc_task", url="BV1xxx", mode="auto", model="small")
        task.status = TaskStatus.processing
        task.started_at = None  # simplified
        storage.save(task)

        recovered = storage.recover(queue)
        assert recovered == 1

        t = queue.peek("proc_task")
        assert t is not None
        assert t.status == TaskStatus.pending  # was reset

    def test_multiple_saves_same_task(self, temp_storage_dir, sample_task):
        """Saving the same task multiple times should overwrite."""
        storage = TaskStorage(temp_storage_dir)

        storage.save(sample_task)
        sample_task.status = TaskStatus.processing
        storage.save(sample_task)
        sample_task.status = TaskStatus.completed
        storage.save(sample_task)

        loaded = storage.load(sample_task.task_id)
        assert loaded.status == TaskStatus.completed

    def test_storage_dir_created(self, temp_storage_dir):
        """Storage directory should be created automatically."""
        nested_dir = os.path.join(temp_storage_dir, "nested", "dir")
        storage = TaskStorage(nested_dir)
        storage.save(Task(task_id="test", url="BV1xxx", mode="auto", model="small"))
        assert os.path.exists(nested_dir)
        assert os.path.exists(os.path.join(nested_dir, "test.json"))