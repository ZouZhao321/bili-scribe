"""后台转录工作者 — 从队列中取出并处理任务。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import urllib.request
from datetime import datetime, timezone
from typing import Optional

# 导入核心转录逻辑
from src.core.bilibili import (
    HEADERS,
    api_get,
    extract_bvid,
    get_cid,
    get_video_info,
    get_subtitle_url,
    download_subtitle_json,
    get_audio_url,
    download_audio,
)
from src.core.transcriber import (
    whisper_transcribe,
    format_timestamp,
)

from src.web.models import (
    OutputFormat,
    ProgressPhase,
    TranscriptMode,
    TranscriptSource,
    TaskStatus,
)
from src.web.queue import queue
from src.web.storage import storage


# 轮询间隔（秒）
POLL_INTERVAL = 2.0


def _progress(task_id: str, phase: ProgressPhase, percent: int, message: str,
              bytes_dl: int | None = None, bytes_total: int | None = None) -> None:
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


def _build_result(bvid: str, title: str, author: str, duration: int,
                  source: TranscriptSource, subtitles: list[dict],
                  total_pages: int, page: int) -> dict:
    """构建标准化的转录结果字典。

    参数：
        bvid: 视频 BV ID。
        title: 视频标题。
        author: 视频作者/UP主。
        duration: 视频时长（秒）。
        source: 转录来源（字幕或 Whisper）。
        subtitles: 字幕片段字典列表。
        total_pages: 视频总页数/分 P 数。
        page: 当前页码。

    返回：
        包含所有转录结果字段的字典。
    """
    entries = len(subtitles)

    if source == TranscriptSource.subtitle:
        full_text = "\n".join(item.get("content", "") for item in subtitles)
    else:
        full_text = "\n".join(item.get("content", "") for item in subtitles)

    return {
        "bvid": bvid,
        "title": title,
        "author": author,
        "duration": duration,
        "source": source.value,
        "total_pages": total_pages,
        "current_page": page,
        "entries": entries,
        "subtitles": subtitles,
        "full_text": full_text,
    }


def _build_usage(source: TranscriptSource, model: str, elapsed: float,
                 audio_duration: int | None = None) -> dict:
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
            {"from": s.get("from", s.get("from_", 0)),
             "to": s.get("to", 0),
             "content": s.get("content", "").strip()}
            for s in subtitles
        ]
    return [
        {"from": s.get("from", s.get("from_", 0)),
         "to": s.get("to", 0),
         "content": s.get("content", "").strip()}
        for s in subtitles
    ]


def process_task(task_id: str) -> None:
    """端到端执行单个转录任务。

    实现三级降级策略：
    1. CC 字幕（秒出）
    2. AI 字幕（秒出）
    3. Whisper 本地转录（CPU，较慢）

    在每个阶段更新进度，完成后持久化结果。

    参数：
        task_id: 要处理的任务的唯一标识符。
    """
    task = queue.peek(task_id)
    if task is None:
        return

    start_time = time.time()

    try:
        bvid = task.url
        # 如果需要，将 URL 解析为 BV ID
        if not bvid.startswith("BV"):
            bvid = extract_bvid(task.url)

        _progress(task_id, ProgressPhase.fetching_info, 10, "正在获取视频信息")

        # 获取视频信息
        video_info = get_video_info(bvid)
        title = video_info.get("title", bvid)
        author = video_info.get("owner", {}).get("name", "")
        duration = video_info.get("duration", 0)

        # 获取 CID
        cid, part_title, total_pages = get_cid(bvid, task.page)

        _progress(task_id, ProgressPhase.fetching_info, 20, f"标题: {title}")

        subtitles = []
        source = TranscriptSource.subtitle

        # 先尝试 CC/AI 字幕
        if task.mode in (TranscriptMode.auto, TranscriptMode.subtitle, TranscriptMode.both):
            sub_list = get_subtitle_url(bvid, cid, task.cookie)
            if sub_list:
                cc_subs = [s for s in sub_list if not s.get("lan", "").startswith("ai")]
                ai_subs = [s for s in sub_list if s.get("lan", "").startswith("ai")]
                ordered = cc_subs + ai_subs

                for sub in ordered:
                    lang = sub.get("lan_doc", sub.get("lan", "unknown"))
                    _progress(task_id, ProgressPhase.fetching_info, 30, f"发现字幕: {lang}")
                    try:
                        sub_data = download_subtitle_json(sub["subtitle_url"])
                        body = sub_data.get("body", [])
                        if body:
                            subtitles = body
                            source = TranscriptSource.subtitle
                            _progress(task_id, ProgressPhase.fetching_info, 40,
                                      f"使用字幕: {len(subtitles)} 条")
                            break
                    except Exception:
                        continue

        # Whisper 降级（或强制）
        need_whisper = (
            task.mode == TranscriptMode.whisper
            or (task.mode == TranscriptMode.both and not subtitles)
            or (task.mode == TranscriptMode.auto and not subtitles)
        )

        whisper_result = None
        if need_whisper:
            _progress(task_id, ProgressPhase.downloading_audio, 50, "正在下载音频流")

            referer = f"https://www.bilibili.com/video/{bvid}/"
            audio_url = get_audio_url(bvid, cid)

            if not audio_url:
                raise RuntimeError("无法获取音频流 URL")

            with tempfile.NamedTemporaryFile(suffix=".m4s", delete=False) as tmp:
                audio_path = tmp.name

            try:
                if not download_audio(audio_url, audio_path, referer):
                    raise RuntimeError("音频下载失败")

                audio_size = os.path.getsize(audio_path)

                _progress(task_id, ProgressPhase.loading_model, 60, f"正在加载 Whisper 模型 ({task.model.value})")

                whisper_result = whisper_transcribe(
                    audio_path,
                    language=task.language,
                    model_size=task.model.value,
                )

                if not whisper_result:
                    raise RuntimeError("Whisper 转录失败")

                _progress(task_id, ProgressPhase.transcribing, 90,
                          f"Whisper 完成: {len(whisper_result)} 个片段")
            finally:
                try:
                    os.unlink(audio_path)
                except OSError:
                    pass

        # 合并结果
        if whisper_result and task.mode == TranscriptMode.both:
            combined = _format_subtitles(whisper_result, task.output_format)
            final_source = TranscriptSource.whisper
            usage_source = TranscriptSource.whisper
        elif whisper_result:
            combined = _format_subtitles(whisper_result, task.output_format)
            final_source = TranscriptSource.whisper
            usage_source = TranscriptSource.whisper
        else:
            combined = _format_subtitles(subtitles, task.output_format)
            final_source = TranscriptSource.subtitle
            usage_source = TranscriptSource.subtitle

        elapsed = time.time() - start_time

        result = _build_result(
            bvid=bvid, title=title, author=author, duration=duration,
            source=final_source, subtitles=combined,
            total_pages=total_pages, page=task.page,
        )

        usage = _build_usage(
            source=usage_source, model=task.model.value,
            elapsed=elapsed, audio_duration=duration if task.mode != TranscriptMode.subtitle else None,
        )

        queue.complete(task_id, result, usage)
        storage.save(queue.peek(task_id))

        _progress(task_id, ProgressPhase.completed, 100, "转录完成")

    except Exception as e:
        elapsed = time.time() - start_time
        error_msg = str(e)
        print(f"[worker] 任务 {task_id} 在 {elapsed:.1f} 秒后失败: {error_msg}", file=sys.stderr)
        queue.fail(task_id, error_msg)
        storage.save(queue.peek(task_id))


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

    payload = {
        "event": f"transcription.{task.status.value}",
        "task_id": task.task_id,
        "status": task.status.value,
    }

    if task.status == TaskStatus.completed:
        payload["result"] = task.result
        payload["usage"] = task.usage
    elif task.status == TaskStatus.failed:
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
        except Exception as e:
            if attempt < max_retries:
                print(f"[worker] Webhook 第 {attempt}/{max_retries} 次尝试失败 ({task_id}): {e}，重试中...", file=sys.stderr)
                time.sleep(2 ** attempt)
            else:
                print(f"[worker] Webhook 发送失败 ({task_id})，已重试 {max_retries} 次: {e}", file=sys.stderr)


class Worker:
    """后台工作者，从队列中取出并处理任务。

    在单个守护线程中运行，避免 Whisper 模型冲突。
    """

    def __init__(self):
        """初始化工作者，不启动线程。"""
        self._thread: Optional[threading.Thread] = None
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
                    storage.save(queue.peek(task.task_id))

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

            except Exception as e:
                print(f"[worker] 意外错误: {e}", file=sys.stderr)
                time.sleep(POLL_INTERVAL)


# 全局单例
worker = Worker()