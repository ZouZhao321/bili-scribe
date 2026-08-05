"""内存任务队列 — 线程安全的队列操作。"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.web.models import (
    OutputFormat,
    ProgressInfo,
    ProgressPhase,
    TaskStatus,
    TranscriptMode,
    WhisperModel,
)

# 默认任务超时时间：6 小时
DEFAULT_TASK_TIMEOUT = 6 * 3600
# 队列最大待处理任务数
MAX_QUEUE_SIZE = 100


@dataclass
class Task:
    """表示单个转录任务。"""

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
    progress: ProgressInfo = field(
        default_factory=lambda: ProgressInfo(phase=ProgressPhase.queued, percent=0, message="等待处理")
    )
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: dict | None = None
    usage: dict | None = None
    error: str | None = None

    def elapsed_seconds(self) -> float:
        """计算自任务创建以来经过的时间。

        返回：
            自创建以来的秒数。
        """
        return (datetime.now(timezone.utc) - self.created_at).total_seconds()

    def is_stale(self, timeout: int = DEFAULT_TASK_TIMEOUT) -> bool:
        """检查运行中的任务是否已超过允许的超时时间。

        参数：
            timeout: 将任务视为僵死前的最大运行时间（秒）。
                默认为 DEFAULT_TASK_TIMEOUT（6 小时）。

        返回：
            如果任务处于处理状态且已超过超时时间则返回 True。
        """
        if self.status != TaskStatus.processing or self.started_at is None:
            return False
        elapsed = (datetime.now(timezone.utc) - self.started_at).total_seconds()
        return elapsed > timeout


class TaskQueue:
    """线程安全的内存任务队列。"""

    def __init__(self, max_size: int = MAX_QUEUE_SIZE):
        self._lock = threading.Lock()
        self._max_size = max_size
        # OrderedDict 维护插入顺序以实现 FIFO
        self._tasks: OrderedDict[str, Task] = OrderedDict()

    # ── 核心操作 ──

    def enqueue(self, task: Task) -> bool:
        """向队列添加任务。

        如果队列已满，或相同 BV ID 的任务已处于待处理/处理中状态，则拒绝添加。

        参数：
            task: 要入队的 Task 实例。

        返回：
            任务添加成功返回 True，被拒绝返回 False。
        """
        with self._lock:
            if len(self._tasks) >= self._max_size:
                return False

            # 去重：同一 BV 只允许一个待处理/处理中的任务
            bvid = self._extract_bvid(task.url)
            if bvid:
                for t in self._tasks.values():
                    if t.status in (TaskStatus.pending, TaskStatus.processing) and self._extract_bvid(t.url) == bvid:
                        return False

            self._tasks[task.task_id] = task
            return True

    def dequeue(self) -> Task | None:
        """按 FIFO 顺序取出下一个待处理任务，并标记为处理中。

        返回：
            下一个待处理的 Task，队列为空则返回 None。
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

    def peek(self, task_id: str) -> Task | None:
        """通过 ID 获取任务，不修改其状态。

        参数：
            task_id: 任务的唯一标识符。

        返回：
            找到则返回 Task，否则返回 None。
        """
        with self._lock:
            return self._tasks.get(task_id)

    def complete(self, task_id: str, result: dict, usage: dict) -> bool:
        """将任务标记为已完成，附带结果和使用数据。

        参数：
            task_id: 任务的唯一标识符。
            result: 转录结果字典。
            usage: 使用统计字典。

        返回：
            找到并更新任务返回 True，否则返回 False。
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            task.status = TaskStatus.completed
            task.completed_at = datetime.now(timezone.utc)
            task.result = result
            task.usage = usage
            task.progress = ProgressInfo(phase=ProgressPhase.completed, percent=100, message="转录完成")
            return True

    def fail(self, task_id: str, error: str) -> bool:
        """将任务标记为失败，附带错误信息。

        参数：
            task_id: 任务的唯一标识符。
            error: 人类可读的错误描述。

        返回：
            找到并更新任务返回 True，否则返回 False。
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            task.status = TaskStatus.failed
            task.completed_at = datetime.now(timezone.utc)
            task.error = error
            task.progress = ProgressInfo(phase=ProgressPhase.failed, percent=0, message=error)
            return True

    def update_progress(
        self,
        task_id: str,
        phase: ProgressPhase,
        percent: int,
        message: str,
        bytes_downloaded: int | None = None,
        bytes_total: int | None = None,
    ) -> bool:
        """更新运行中任务的进度信息。

        参数：
            task_id: 任务的唯一标识符。
            phase: 当前进度阶段。
            percent: 进度百分比（0-100）。
            message: 人类可读的进度消息。
            bytes_downloaded: 可选，已下载的字节数。
            bytes_total: 可选，总下载字节数。

        返回：
            找到并更新任务返回 True，否则返回 False。
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            task.progress = ProgressInfo(
                phase=phase,
                percent=percent,
                message=message,
                bytes_downloaded=bytes_downloaded,
                bytes_total=bytes_total,
            )
            return True

    # ── 查询操作 ──

    def list(self, status: str | None = None, limit: int = 20, offset: int = 0) -> tuple[list[Task], int]:
        """列出任务，支持可选的状态过滤和分页。

        参数：
            status: 可选的状态过滤（'pending'、'processing'、
                'completed'、'failed'）。为 None 时返回所有状态。
            limit: 返回的最大任务数（默认 20）。
            offset: 分页跳过的任务数。

        返回：
            (Task 列表, 匹配过滤条件的总数) 元组。
        """
        with self._lock:
            all_tasks = list(self._tasks.values())

            if status:
                all_tasks = [t for t in all_tasks if t.status.value == status]

            # 按 created_at 降序排序
            all_tasks.sort(key=lambda t: t.created_at, reverse=True)

            total = len(all_tasks)
            paginated = all_tasks[offset : offset + limit]
            return paginated, total

    def stats(self) -> dict[str, int]:
        """获取按状态分类的队列统计信息。

        返回：
            包含 'pending'、'processing'、'completed'、
            'failed' 键及其对应计数的字典。
        """
        with self._lock:
            counts = {"pending": 0, "processing": 0, "completed": 0, "failed": 0}
            for task in self._tasks.values():
                status = task.status.value
                if status in counts:
                    counts[status] += 1
            return counts

    def remove(self, task_id: str) -> bool:
        """通过 ID 从队列中移除任务。

        参数：
            task_id: 要移除的任务的唯一标识符。

        返回：
            找到并移除任务返回 True，否则返回 False。
        """
        with self._lock:
            if task_id in self._tasks:
                del self._tasks[task_id]
                return True
            return False

    # ── 维护 ──

    def detect_stale_tasks(self, timeout: int = DEFAULT_TASK_TIMEOUT) -> list[Task]:
        """查找并返回所有已超过超时时间的处理中任务。

        参数：
            timeout: 最大允许运行时间（秒）。

        返回：
            僵死 Task 实例的列表。
        """
        stale = []
        with self._lock:
            for task in self._tasks.values():
                if task.is_stale(timeout):
                    stale.append(task)
        return stale

    def size(self) -> int:
        """获取队列中当前的任务总数。

        返回：
            任务数量（所有状态）。
        """
        with self._lock:
            return len(self._tasks)

    # ── 辅助方法 ──

    @staticmethod
    def _extract_bvid(url: str) -> str | None:
        """从 B 站 URL 或纯 ID 字符串中提取 BV ID。

        参数：
            url: B 站 URL 或 BV ID 字符串。

        返回：
            找到则返回 12 位 BV ID，否则返回 None。
        """
        import re

        m = re.search(r"(BV[\w]{10})", url)
        return m.group(1) if m else None


# 全局单例
queue = TaskQueue()
