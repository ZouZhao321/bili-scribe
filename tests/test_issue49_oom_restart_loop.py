"""issue 49：OOM 击杀 + 容器重启导致同一任务无限重做。

模拟内核 OOM 用 SIGKILL 终止进程的场景：任务在磁盘上停留于 processing，
进程没有任何机会调用 queue.fail()。重启后 recover() 把任务改回 pending，
worker 立刻再次取走，循环不收敛。
"""

from __future__ import annotations

from bili_scribe.web.models import (
    OutputFormat,
    TaskStatus,
    TranscriptMode,
    WhisperModel,
)
from bili_scribe.web.queue import Task, TaskQueue
from bili_scribe.web.storage import TaskStorage

# 容器实测的重启次数上限，循环不应超过该次数
RESTART_BUDGET = 10


def _make_task(task_id: str = "oom_loop_001") -> Task:
    return Task(
        task_id=task_id,
        url="https://www.bilibili.com/video/BV1Gm421W75K",
        mode=TranscriptMode.auto,
        model=WhisperModel.medium,
        language="zh",
        page=0,
        output_format=OutputFormat.text,
    )


def test_oom_restart_loop_reaches_terminal_state(temp_storage_dir):
    """500 次「取任务 → 被击杀 → 重启恢复」之后，任务必须停在终态。"""
    store = TaskStorage(temp_storage_dir)

    q = TaskQueue()
    task = _make_task()
    assert q.enqueue(task)
    store.save(task)

    restarts = 0
    for _ in range(500):
        picked = q.dequeue()
        if picked is None:
            break
        store.save(picked)  # 持久化 processing 状态

        # SIGKILL：进程消失，queue.fail() 不会被调用
        q = TaskQueue()
        store.recover(q)
        restarts += 1

    final = q.peek(task.task_id)
    assert final is not None
    assert restarts <= RESTART_BUDGET, f"任务被重做 {restarts} 次仍未收敛"
    assert final.status in (TaskStatus.failed, TaskStatus.completed), f"停留于 {final.status}"
    assert final.error, "进入终态时必须附带原因"


def test_recover_counts_attempts_on_disk(temp_storage_dir):
    """恢复被中断的任务时，磁盘上的尝试次数必须递增。"""
    store = TaskStorage(temp_storage_dir)

    q = TaskQueue()
    task = _make_task("oom_loop_002")
    assert q.enqueue(task)
    store.save(task)

    picked = q.dequeue()
    store.save(picked)

    q2 = TaskQueue()
    store.recover(q2)

    on_disk = store.load("oom_loop_002")
    assert on_disk is not None
    assert getattr(on_disk, "attempts", None) == 1, "尝试次数未持久化"


def test_recover_keeps_untouched_pending_task_pending(temp_storage_dir):
    """正常的 pending 任务不受尝试次数机制影响。"""
    store = TaskStorage(temp_storage_dir)

    q = TaskQueue()
    task = _make_task("oom_loop_003")
    assert q.enqueue(task)
    store.save(task)

    q2 = TaskQueue()
    store.recover(q2)

    recovered = q2.peek("oom_loop_003")
    assert recovered is not None
    assert recovered.status == TaskStatus.pending
    assert getattr(recovered, "attempts", 0) == 0
