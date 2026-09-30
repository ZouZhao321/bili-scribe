"""issue 49：OOM 循环的三道防线。

1. recover() 的尝试次数上限与 OOM 击杀判定（test_issue49_oom_restart_loop.py 覆盖循环本身）
2. 可用内存以容器 cgroup 限额为准，而不是 /proc/meminfo
3. 并发线程共享内存预留，避免各自读到同一份「资源充足」的结论
"""

from __future__ import annotations

from bili_scribe.core import queue_store
from bili_scribe.web.models import (
    OutputFormat,
    TaskStatus,
    TranscriptMode,
    WhisperModel,
)
from bili_scribe.web.queue import Task, TaskQueue
from bili_scribe.web.storage import TaskStorage

GIB = 1024 * 1024 * 1024


def _make_task(task_id: str = "mem_guard_001") -> Task:
    return Task(
        task_id=task_id,
        url="https://www.bilibili.com/video/BV1Gm421W75K",
        mode=TranscriptMode.auto,
        model=WhisperModel.medium,
        language="zh",
        page=0,
        output_format=OutputFormat.text,
    )


# ── 1. OOM 击杀判定 ──


def test_recover_marks_failed_when_oom_killed(temp_storage_dir):
    """容器记录过 OOM 击杀时，被中断的任务直接停在终态，不再重做。"""
    store = TaskStorage(temp_storage_dir)

    q = TaskQueue()
    task = _make_task()
    assert q.enqueue(task)
    store.save(task)

    picked = q.dequeue()
    assert picked is not None
    store.save(picked)

    restarted = TaskQueue()
    store.recover(restarted, oom_killed=True)

    final = restarted.peek(task.task_id)
    assert final is not None
    assert final.status == TaskStatus.failed
    assert final.completed_at is not None
    assert "OOM" in final.error


def test_oom_killed_leaves_pending_task_pending(temp_storage_dir):
    """OOM 击杀只影响被中断的任务，未曾开始执行的任务照常等待。"""
    store = TaskStorage(temp_storage_dir)

    q = TaskQueue()
    waiting = _make_task("mem_guard_pending")
    assert q.enqueue(waiting)
    store.save(waiting)

    restarted = TaskQueue()
    store.recover(restarted, oom_killed=True)

    final = restarted.peek("mem_guard_pending")
    assert final is not None
    assert final.status == TaskStatus.pending


def test_attempts_survive_round_trip(temp_storage_dir):
    """尝试次数必须能被写入磁盘并读回。"""
    store = TaskStorage(temp_storage_dir)

    task = _make_task("mem_guard_attempts")
    task.attempts = 7
    store.save(task)

    loaded = store.load("mem_guard_attempts")
    assert loaded is not None
    assert loaded.attempts == 7


# ── 2. cgroup 内存 ──


def test_cgroup_limit_and_usage_are_read(tmp_path, monkeypatch):
    """cgroup v2 的限额与用量按 MiB 向上取整到 MB。"""
    limit_file = tmp_path / "memory.max"
    usage_file = tmp_path / "memory.current"
    limit_file.write_text(str(8 * GIB))
    usage_file.write_text(str(7 * GIB))
    monkeypatch.setattr(queue_store, "CGROUP_V2_LIMIT", str(limit_file))
    monkeypatch.setattr(queue_store, "CGROUP_V2_USAGE", str(usage_file))

    assert queue_store.get_cgroup_memory_limit_mb() == 8192
    assert queue_store.get_cgroup_memory_usage_mb() == 7168
    assert queue_store.get_available_memory_mb() == 1024


def test_cgroup_max_means_no_limit(tmp_path, monkeypatch):
    """cgroup v2 的 "max" 表示无限制，应视为读不到限额。"""
    limit_file = tmp_path / "memory.max"
    limit_file.write_text("max")
    monkeypatch.setattr(queue_store, "CGROUP_V2_LIMIT", str(limit_file))
    monkeypatch.setattr(queue_store, "CGROUP_V1_LIMIT", str(tmp_path / "absent"))

    assert queue_store.get_cgroup_memory_limit_mb() is None


def test_oom_kill_count_is_read(tmp_path, monkeypatch):
    """memory.events 的 oom_kill 字段决定容器是否被 OOM 击杀过。"""
    events_file = tmp_path / "memory.events"
    events_file.write_text("low 0\nhigh 12\nmax 4\noom 3\noom_kill 3\noom_group_kill 0\n")
    monkeypatch.setattr(queue_store, "CGROUP_V2_EVENTS", str(events_file))
    monkeypatch.setattr(queue_store, "CGROUP_V1_EVENTS", str(tmp_path / "absent"))

    assert queue_store.get_oom_kill_count() == 3


def test_oom_kill_count_zero_without_cgroup(tmp_path, monkeypatch):
    """不在容器内运行时不报告 OOM 击杀。"""
    monkeypatch.setattr(queue_store, "CGROUP_V2_EVENTS", str(tmp_path / "absent"))
    monkeypatch.setattr(queue_store, "CGROUP_V1_EVENTS", str(tmp_path / "absent"))

    assert queue_store.get_oom_kill_count() == 0


def test_oom_kill_zero_in_v2_does_not_fall_back(tmp_path, monkeypatch):
    """cgroup v2 明确读到 0 时不得回退去读 v1 的历史值。"""
    v2_events = tmp_path / "memory.events"
    v2_events.write_text("low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\noom_group_kill 0\n")
    v1_events = tmp_path / "memory.oom_control"
    v1_events.write_text("oom_kill_disable 0\nunder_oom 0\noom_kill 7\n")
    monkeypatch.setattr(queue_store, "CGROUP_V2_EVENTS", str(v2_events))
    monkeypatch.setattr(queue_store, "CGROUP_V1_EVENTS", str(v1_events))

    assert queue_store.get_oom_kill_count() == 0


# ── 3. 并发线程共享内存预留 ──


def test_concurrent_threads_share_memory_budget(monkeypatch):
    """首个线程通过判定后，第二个线程不能再拿到同一份可用内存。"""
    from bili_scribe.web import worker as worker_module

    monkeypatch.setattr(worker_module, "get_available_memory_mb", lambda: 4000)
    monkeypatch.setattr(worker_module, "get_cpu_usage", lambda: 0)

    w = worker_module.Worker(num_workers=2)
    first_ok, _ = w._check_resources("medium")
    second_ok, second_reason = w._check_resources("medium")

    assert first_ok is True
    assert second_ok is False
    assert "预留" in second_reason


def test_release_returns_memory_to_the_pool(monkeypatch):
    """任务结束后预留内存归还，后续任务可以重新通过判定。"""
    from bili_scribe.web import worker as worker_module

    monkeypatch.setattr(worker_module, "get_available_memory_mb", lambda: 4000)
    monkeypatch.setattr(worker_module, "get_cpu_usage", lambda: 0)

    w = worker_module.Worker(num_workers=2)
    assert w._check_resources("medium")[0] is True
    assert w._check_resources("medium")[0] is False

    w._release_memory("medium")
    assert w._check_resources("medium")[0] is True


def test_memory_budget_report_lists_infeasible_models(monkeypatch, capsys):
    """启动报告必须点出在当前并发配置下必然超限的模型。"""
    from bili_scribe.web import worker as worker_module

    monkeypatch.setattr(worker_module, "get_cgroup_memory_limit_mb", lambda: 4096)
    worker_module.report_memory_budget(2)

    err = capsys.readouterr().err
    assert "单线程预算 2048MB" in err
    warning_lines = [line for line in err.splitlines() if "警告" in line]
    assert warning_lines, f"未给出限额警告: {err}"
    assert "medium" in warning_lines[0]
    assert "large-v3" in warning_lines[0]
    assert "base" not in warning_lines[0]


# ── 4. 重试重置尝试次数 ──


def test_retry_resets_attempts(api_client):
    """用户手动重试必须清空尝试次数，否则调大内存后仍会立刻失败。"""
    from bili_scribe.web.queue import queue

    task = _make_task("mem_guard_retry")
    task.status = TaskStatus.failed
    task.attempts = 3
    task.error = "任务第 3 次执行时容器内存不足，进程被内核 OOM 击杀"
    assert queue.enqueue(task)

    response = api_client.post("/api/v1/tasks/mem_guard_retry/retry")

    assert response.status_code == 200
    reset = queue.peek("mem_guard_retry")
    assert reset is not None
    assert reset.status == TaskStatus.pending
    assert reset.attempts == 0
    assert reset.error is None


def test_release_returns_task_to_pending_without_burning_attempts():
    """资源不足而退回的任务不应消耗尝试次数配额。"""
    q = TaskQueue()
    task = _make_task("mem_guard_release")
    assert q.enqueue(task)

    picked = q.dequeue()
    assert picked is not None
    assert picked.attempts == 1

    assert q.release("mem_guard_release") is True
    returned = q.peek("mem_guard_release")
    assert returned is not None
    assert returned.status == TaskStatus.pending
    assert returned.attempts == 0
    assert returned.started_at is None


# ── 5. 服务启动的完整恢复链路 ──


def test_server_startup_stops_oom_loop(tmp_path, monkeypatch):
    """服务在 OOM 击杀后重启时，被中断的任务停在失败状态，不会被再次取走。"""
    from fastapi.testclient import TestClient

    from bili_scribe.web import server as server_module
    from bili_scribe.web.queue import queue
    from bili_scribe.web.server import app
    from bili_scribe.web.storage import storage

    monkeypatch.setattr(storage, "_dir", str(tmp_path))
    with queue._lock:
        queue._tasks.clear()

    # 磁盘上留下被 OOM 击杀时正在处理的任务
    store = TaskStorage(str(tmp_path))
    interrupted = _make_task("startup_oom_001")
    interrupted.status = TaskStatus.processing
    interrupted.attempts = 1
    store.save(interrupted)

    # 容器 cgroup 记录过一次 OOM 击杀
    monkeypatch.setattr(server_module, "get_oom_kill_count", lambda: 1)

    with TestClient(app):
        final = queue.peek("startup_oom_001")
        assert final is not None
        assert final.status == TaskStatus.failed
        assert final.error is not None
        assert "OOM" in final.error
        on_disk = store.load("startup_oom_001")
        assert on_disk is not None
        assert on_disk.status == TaskStatus.failed
