"""后台转录工作者 — 从队列中取出并处理任务。"""

from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any

# 导入核心转录逻辑
from src.core.runner import run_transcription
from src.core.queue_store import (
    CPU_THRESHOLD,
    MEMORY_THRESHOLD,
    MODEL_MEMORY_REQUIREMENTS,
    get_available_memory_mb,
    get_cpu_usage,
)
from src.web.models import (
    OutputFormat,
    ProgressPhase,
    TaskStatus,
    TranscriptSource,
)
from src.web.queue import queue
from src.web.storage import storage

# 轮询间隔（秒）：无任务或资源不足时等待时间
POLL_INTERVAL = 30.0


def _progress(
    task_id: str,
    phase: ProgressPhase,
    percent: int,
    message: str,
    bytes_dl: int | None = None,
    bytes_total: int | None = None,
) -> None:
    """更新任务进度并持久化到磁盘。

    参数：
        task_id: 任务的唯一标识符。
        phase: 当前进度阶段。
        percent: 进度百分比（0-100）。
        message: 人类可读的进度消息。
        bytes_dl: 可选，已下载的字节数。
        bytes_total: 可选，总下载字节数。
    """
    queue.update_progress(task_id, phase, percent, message, bytes_dl, bytes_total)
    task = queue.peek(task_id)
    if task:
        storage.save(task)


def _build_usage(source: TranscriptSource, model: str, elapsed: float, audio_duration: int | None = None) -> dict:
    """构建标准化的使用统计字典。

    参数：
        source: 转录来源。
        model: Whisper 模型名称（字幕来源时为空字符串）。
        elapsed: 转录花费的挂钟时间（秒）。
        audio_duration: 可选，音频时长，用于计算实时因子。

    返回：
        包含使用统计信息的字典。
    """
    info = {
        "source": source.value,
        "model": model if source == TranscriptSource.whisper else "",
        "duration_seconds": round(elapsed, 2),
    }
    if audio_duration and source == TranscriptSource.whisper:
        info["audio_duration"] = audio_duration
        info["real_time_factor"] = round(elapsed / audio_duration, 2) if audio_duration > 0 else None
    return info


def _format_subtitles(subtitles: list[dict], fmt: OutputFormat) -> list[dict]:
    """根据请求的输出格式格式化字幕片段。

    参数：
        subtitles: 来自转录引擎的原始字幕片段列表。
        fmt: 目标输出格式。

    返回：
        包含 'from'、'to' 和 'content' 键的格式化字幕字典列表。
    """
    if fmt == OutputFormat.json:
        return [
            {"from": s.get("from", s.get("from_", 0)), "to": s.get("to", 0), "content": s.get("content", "").strip()}
            for s in subtitles
        ]
    return [
        {"from": s.get("from", s.get("from_", 0)), "to": s.get("to", 0), "content": s.get("content", "").strip()}
        for s in subtitles
    ]


def process_task(task_id: str) -> None:
    """端到端执行单个转录任务。

    调用核心引擎 run_transcription() 执行三级降级转录，
    结果写入 out/ 目录并填充到任务 result 字段。

    参数：
        task_id: 要处理的任务的唯一标识符。
    """
    task = queue.peek(task_id)
    if task is None:
        return

    start_time = time.time()

    try:
        _progress(task_id, ProgressPhase.fetching_info, 10, "正在获取视频信息")

        # 调用核心转录引擎（三级降级 → 写入 out/ 目录）
        result = run_transcription(
            url=task.url,
            model=task.model.value,
            task_id=task_id,
            mode=task.mode.value,
            language=task.language,
            page=task.page,
            cookie=task.cookie,
        )

        if not result["success"]:
            raise RuntimeError(result["error"])

        elapsed = time.time() - start_time

        # 构建 API 响应格式
        source = TranscriptSource(result["source"])
        formatted_subtitles = _format_subtitles(result["subtitles"], task.output_format)

        api_result = {
            "bvid": result["bv"],
            "title": result["title"],
            "author": result["author"],
            "duration": result["duration"],
            "source": source.value,
            "total_pages": 1,
            "current_page": task.page,
            "entries": result["lines"],
            "subtitles": formatted_subtitles,
            "full_text": result["full_text"],
        }

        usage = _build_usage(
            source=source,
            model=task.model.value,
            elapsed=elapsed,
            audio_duration=result["duration"] if source == TranscriptSource.whisper else None,
        )

        queue.complete(task_id, api_result, usage)
        completed = queue.peek(task_id)
        if completed:
            storage.save(completed)

        _progress(task_id, ProgressPhase.completed, 100, "转录完成")

    except Exception as e:  # noqa: BLE001
        elapsed = time.time() - start_time
        error_msg = str(e)
        print(f"[worker] 任务 {task_id} 在 {elapsed:.1f} 秒后失败: {error_msg}", file=sys.stderr)
        queue.fail(task_id, error_msg)
        failed = queue.peek(task_id)
        if failed:
            storage.save(failed)


def _fire_webhook(task_id: str) -> None:
    """为已完成或失败的任务发送 webhook 回调。

    最多重试 3 次，使用指数退避（2 秒、4 秒、8 秒）。
    回调负载包含转录结果或错误信息。

    参数：
        task_id: 已完成/失败的任务的唯一标识符。
    """
    task = queue.peek(task_id)
    if not task or not task.webhook:
        return

    payload: dict[str, Any] = {
        "event": f"transcription.{task.status.value}",
        "task_id": task.task_id,
        "status": task.status.value,
    }

    if task.status == TaskStatus.completed:
        if task.result:
            payload["result"] = task.result
        if task.usage:
            payload["usage"] = task.usage
    elif task.status == TaskStatus.failed:
        if task.error:
            payload["error"] = task.error
            payload["message"] = task.error

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(
                task.webhook,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                print(f"[worker] Webhook 已发送到 {task.webhook}: {resp.status}", file=sys.stderr)
                return
        except urllib.error.URLError as e:
            if attempt < max_retries:
                print(
                    f"[worker] Webhook 第 {attempt}/{max_retries} 次尝试失败 ({task_id}): {e}，重试中...",
                    file=sys.stderr,
                )
                time.sleep(2**attempt)
            else:
                print(f"[worker] Webhook 发送失败 ({task_id})，已重试 {max_retries} 次: {e}", file=sys.stderr)


class Worker:
    """后台工作者，从队列中取出并处理任务。

    在单个守护线程中运行，避免 Whisper 模型冲突。
    """

    def __init__(self):
        """初始化工作者，不启动线程。"""
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        """启动后台工作者线程。

        启动单个守护线程，轮询队列中的待处理任务。
        多次调用安全——后续调用无操作。
        """
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="transcribe-worker")
        self._thread.start()
        print("[worker] 已启动", file=sys.stderr)

    def stop(self) -> None:
        """通知工作者在完成当前任务后停止。

        将运行标志设置为 False；工作循环将在下一次迭代时退出。
        """
        self._running = False
        print("[worker] 正在停止...", file=sys.stderr)

    @property
    def is_running(self) -> bool:
        """检查工作者线程当前是否活跃。"""
        return self._running

    def _check_resources(self, model: str) -> tuple[bool, str]:
        """检查 CPU 和内存是否满足任务执行条件.

        参数：
            model: Whisper 模型名称（用于内存需求计算）

        返回：
            (是否满足, 不满足原因) 元组
        """
        cpu = get_cpu_usage()
        if cpu > CPU_THRESHOLD:
            return False, f"CPU {cpu}% > 阈值 {CPU_THRESHOLD}%"

        mem_avail = get_available_memory_mb()
        mem_required = MODEL_MEMORY_REQUIREMENTS.get(model, 2000)
        mem_needed = int(mem_required * MEMORY_THRESHOLD)
        if mem_avail < mem_needed:
            return False, f"内存不足: 可用 {mem_avail}MB < 需要 {mem_needed}MB (模型 {model})"

        return True, ""

    def _run(self) -> None:
        """主工作循环 — 轮询队列并处理任务。

        无限运行直到调用 stop()。每次迭代：
        1. 检测并标记僵死任务为失败。
        2. 取出下一个待处理任务。
        3. 通过 process_task() 处理。
        4. 如果配置了 webhook，则触发回调。
        """
        while self._running:
            try:
                # 检查僵死任务
                stale = queue.detect_stale_tasks()
                for task in stale:
                    print(f"[worker] 检测到僵死任务: {task.task_id}", file=sys.stderr)
                    queue.fail(task.task_id, "转录超时")
                    stale_task = queue.peek(task.task_id)
                    if stale_task:
                        storage.save(stale_task)

                # 检查是否有待处理任务
                pending_tasks, _ = queue.list(status="pending", limit=1)
                if not pending_tasks:
                    time.sleep(POLL_INTERVAL)
                    continue

                # 资源检查：CPU 和内存
                pending = pending_tasks[0]
                model = pending.model.value if hasattr(pending.model, 'value') else str(pending.model)
                ok, reason = self._check_resources(model)
                if not ok:
                    print(f"[worker] 资源不足，跳过: {reason}", file=sys.stderr)
                    time.sleep(POLL_INTERVAL)
                    continue

                # 取出下一个任务
                task = queue.dequeue()
                if task is None:
                    time.sleep(POLL_INTERVAL)
                    continue

                task_id = task.task_id
                print(f"[worker] 正在处理: {task_id} (url={task.url}, mode={task.mode})", file=sys.stderr)

                # 处理
                process_task(task_id)

                # 如果配置了 webhook，则触发
                _fire_webhook(task_id)

            except Exception as e:  # noqa: BLE001
                print(f"[worker] 意外错误: {e}", file=sys.stderr)
                time.sleep(POLL_INTERVAL)


# 全局单例
worker = Worker()
