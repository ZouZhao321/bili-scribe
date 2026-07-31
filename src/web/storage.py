"""任务持久化存储 — 将任务状态保存到磁盘 JSON 文件。"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path

from src.web.models import (
    OutputFormat,
    ProgressInfo,
    ProgressPhase,
    TaskStatus,
    TranscriptMode,
    WhisperModel,
)
from src.web.queue import Task, TaskQueue

# 默认存储目录
DEFAULT_STORAGE_DIR = os.path.expanduser("~/.bilibili-api/tasks")


def _serialize_task(task: Task) -> dict:
    """将 Task 实例序列化为可 JSON 序列化的字典。

    将所有枚举字段转换为字符串值，日期时间字段转换为 ISO 格式字符串。
    为兼容恢复过程，同时处理枚举实例和原始字符串值。

    参数：
        task: 要序列化的 Task 实例。

    返回：
        适合 JSON 序列化的字典。
    """
    return {
        "task_id": task.task_id,
        "url": task.url,
        "mode": task.mode.value if isinstance(task.mode, TranscriptMode) else task.mode,
        "model": task.model.value if isinstance(task.model, WhisperModel) else task.model,
        "language": task.language,
        "page": task.page,
        "output_format": task.output_format.value
        if isinstance(task.output_format, OutputFormat)
        else task.output_format,
        "cookie": task.cookie,
        "webhook": task.webhook,
        "status": task.status.value if isinstance(task.status, TaskStatus) else task.status,
        "progress": {
            "phase": task.progress.phase.value
            if isinstance(task.progress.phase, ProgressPhase)
            else task.progress.phase,
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
    """将字典反序列化为 Task 实例。

    处理 ISO 格式日期时间字符串、字符串枚举值和嵌套的进度信息。
    缺失的可选字段使用合理的默认值。

    参数：
        data: 表示序列化任务的字典。

    返回：
        重建的 Task 实例。
    """
    progress_data = data.get("progress", {})
    progress = ProgressInfo(
        phase=progress_data.get("phase", "queued"),
        percent=progress_data.get("percent", 0),
        message=progress_data.get("message", ""),
        bytes_downloaded=progress_data.get("bytes_downloaded"),
        bytes_total=progress_data.get("bytes_total"),
    )

    def _parse_dt(val):
        """从 ISO 格式字符串解析日期时间，或原样返回。

        参数：
            val: datetime 实例、ISO 格式字符串或 None。

        返回：
            解析成功则返回 datetime 实例，否则返回 None。
        """
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
    """将任务状态持久化到磁盘的 JSON 文件中。

    每个任务存储为独立的 JSON 文件：<storage_dir>/<task_id>.json
    启动时加载所有文件并恢复到队列中。
    """

    def __init__(self, storage_dir: str = DEFAULT_STORAGE_DIR):
        self._dir = storage_dir
        self._lock = threading.Lock()

    @property
    def dir(self) -> str:
        """获取存储目录路径。"""
        return self._dir

    def ensure_dir(self) -> None:
        """创建存储目录（及父目录），如果不存在的话。"""
        Path(self._dir).mkdir(parents=True, exist_ok=True)

    def save(self, task: Task) -> None:
        """将单个任务持久化到磁盘的 JSON 文件。

        文件写入 <storage_dir>/<task_id>.json。

        参数：
            task: 要保存的 Task 实例。
        """
        self.ensure_dir()
        filepath = os.path.join(self._dir, f"{task.task_id}.json")
        data = _serialize_task(task)
        with self._lock:
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except OSError as e:
                print(f"[storage] 保存任务 {task.task_id} 失败: {e}", file=__import__("sys").stderr)

    def load(self, task_id: str) -> Task | None:
        """通过 ID 从磁盘加载单个任务。

        参数：
            task_id: 任务的唯一标识符。

        返回：
            找到则返回反序列化的 Task，否则返回 None。
        """
        filepath = os.path.join(self._dir, f"{task_id}.json")
        if not os.path.exists(filepath):
            return None
        with self._lock:
            try:
                with open(filepath, encoding="utf-8") as f:
                    data = json.load(f)
                return _deserialize_task(data)
            except (json.JSONDecodeError, KeyError):
                return None

    def delete(self, task_id: str) -> bool:
        """从磁盘删除任务文件。

        参数：
            task_id: 要删除的任务的唯一标识符。

        返回：
            文件删除成功返回 True，文件不存在或删除失败返回 False。
        """
        filepath = os.path.join(self._dir, f"{task_id}.json")
        try:
            if os.path.exists(filepath):
                with self._lock:
                    os.remove(filepath)
                return True
        except OSError as e:
            print(f"[storage] 删除任务 {task_id} 失败: {e}", file=__import__("sys").stderr)
        return False

    def recover(self, queue: TaskQueue) -> int:
        """从磁盘加载所有已保存的任务，恢复到队列中。

        已完成和失败的任务加载用于查询。
        待处理的任务重新入队。
        处理中的任务重置为待处理，确保安全恢复。

        参数：
            queue: 要恢复任务的 TaskQueue 实例。

        返回：
            从磁盘恢复的任务数量。
        """
        self.ensure_dir()
        recovered = 0
        try:
            filenames = os.listdir(self._dir)
        except OSError as e:
            print(f"[storage] 列出存储目录失败: {e}", file=__import__("sys").stderr)
            return 0

        for filename in filenames:
            if not filename.endswith(".json"):
                continue
            task_id = filename[:-5]
            task = self.load(task_id)
            if task is None:
                continue

            # 将处理中的任务重置为待处理，确保安全恢复
            if task.status == TaskStatus.processing:
                task.status = TaskStatus.pending
                task.started_at = None
                task.progress = ProgressInfo(phase=ProgressPhase.queued, percent=0, message="等待处理（重启恢复）")

            # 重新添加到队列（如果存在则覆盖）
            existing = queue.peek(task_id)
            if existing is None:
                queue.enqueue(task)

            recovered += 1

        return recovered

    def list_files(self) -> list[str]:
        """列出已持久化到磁盘的所有任务 ID。

        返回：
            排序后的任务 ID 字符串列表。
        """
        self.ensure_dir()
        tasks = []
        try:
            filenames = sorted(os.listdir(self._dir))
        except OSError as e:
            print(f"[storage] 列出存储目录失败: {e}", file=__import__("sys").stderr)
            return tasks
        for filename in filenames:
            if filename.endswith(".json"):
                tasks.append(filename[:-5])
        return tasks


# 全局单例
storage = TaskStorage()
