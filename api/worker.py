"""Background transcription worker — processes tasks from the queue."""

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

# Import core transcription logic
from fetch_transcript import (
    HEADERS,
    api_get,
    extract_bvid,
    get_cid,
    get_video_info,
    get_subtitle_url,
    download_subtitle_json,
    get_audio_url,
    download_audio,
    whisper_transcribe,
    format_timestamp,
)

from api.models import (
    OutputFormat,
    ProgressPhase,
    TranscriptMode,
    TranscriptSource,
    TaskStatus,
)
from api.queue import queue
from api.storage import storage


# Check interval in seconds
POLL_INTERVAL = 2.0


def _progress(task_id: str, phase: ProgressPhase, percent: int, message: str,
              bytes_dl: int | None = None, bytes_total: int | None = None) -> None:
    """Helper to update progress and persist."""
    queue.update_progress(task_id, phase, percent, message, bytes_dl, bytes_total)
    task = queue.peek(task_id)
    if task:
        storage.save(task)


def _build_result(bvid: str, title: str, author: str, duration: int,
                  source: TranscriptSource, subtitles: list[dict],
                  total_pages: int, page: int) -> dict:
    """Build a standardized result dict from subtitles."""
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
    """Build a standardized usage dict."""
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
    """Format subtitles according to the requested output format."""
    if fmt == OutputFormat.json:
        # Return raw subtitles with both from/to and content
        return [
            {"from": s.get("from", s.get("from_", 0)),
             "to": s.get("to", 0),
             "content": s.get("content", "").strip()}
            for s in subtitles
        ]
    # For text and timestamps formats, return the same structure
    # The caller (API route) will handle formatting
    return [
        {"from": s.get("from", s.get("from_", 0)),
         "to": s.get("to", 0),
         "content": s.get("content", "").strip()}
        for s in subtitles
    ]


def process_task(task_id: str) -> None:
    """Execute a single transcription task. Called by the worker thread."""
    task = queue.peek(task_id)
    if task is None:
        return

    start_time = time.time()

    try:
        bvid = task.url
        # Resolve URL to BV ID if needed
        if not bvid.startswith("BV"):
            bvid = extract_bvid(task.url)

        _progress(task_id, ProgressPhase.fetching_info, 10, "正在获取视频信息")

        # Get video info
        video_info = get_video_info(bvid)
        title = video_info.get("title", bvid)
        author = video_info.get("owner", {}).get("name", "")
        duration = video_info.get("duration", 0)

        # Get CID
        cid, part_title, total_pages = get_cid(bvid, task.page)

        _progress(task_id, ProgressPhase.fetching_info, 20, f"标题: {title}")

        subtitles = []
        source = TranscriptSource.subtitle

        # Try CC/AI subtitles first
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

        # Whisper fallback (or forced)
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

        # Combine results
        if whisper_result and task.mode == TranscriptMode.both:
            # both mode: use whisper as primary, note subtitle availability
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
        print(f"[worker] Task {task_id} failed after {elapsed:.1f}s: {error_msg}", file=sys.stderr)
        queue.fail(task_id, error_msg)
        storage.save(queue.peek(task_id))


def _fire_webhook(task_id: str) -> None:
    """Fire webhook callback for a completed/failed task. Retries up to 3 times."""
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
                print(f"[worker] Webhook sent to {task.webhook}: {resp.status}", file=sys.stderr)
                return  # success
        except Exception as e:
            if attempt < max_retries:
                print(f"[worker] Webhook attempt {attempt}/{max_retries} failed for {task_id}: {e}, retrying...", file=sys.stderr)
                time.sleep(2 ** attempt)  # exponential backoff
            else:
                print(f"[worker] Webhook failed for {task_id} after {max_retries} attempts: {e}", file=sys.stderr)


class Worker:
    """Background worker that processes tasks from the queue.

    Runs in a single daemon thread to avoid Whisper model conflicts.
    """

    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> None:
        """Start the worker thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="transcribe-worker")
        self._thread.start()
        print("[worker] Started", file=sys.stderr)

    def stop(self) -> None:
        """Signal the worker to stop."""
        self._running = False
        print("[worker] Stopping...", file=sys.stderr)

    @property
    def is_running(self) -> bool:
        return self._running

    def _run(self) -> None:
        """Main worker loop."""
        while self._running:
            try:
                # Check for stale tasks
                stale = queue.detect_stale_tasks()
                for task in stale:
                    print(f"[worker] Stale task detected: {task.task_id}", file=sys.stderr)
                    queue.fail(task.task_id, "转录超时")
                    storage.save(queue.peek(task.task_id))

                # Dequeue next task
                task = queue.dequeue()
                if task is None:
                    time.sleep(POLL_INTERVAL)
                    continue

                task_id = task.task_id
                print(f"[worker] Processing: {task_id} (url={task.url}, mode={task.mode})", file=sys.stderr)

                # Process
                process_task(task_id)

                # Fire webhook if configured
                _fire_webhook(task_id)

            except Exception as e:
                print(f"[worker] Unexpected error: {e}", file=sys.stderr)
                time.sleep(POLL_INTERVAL)


# Global singleton
worker = Worker()