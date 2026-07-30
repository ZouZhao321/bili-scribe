"""Transcribe endpoints — submit transcription tasks and query results."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status

from src.fetch_transcript import (
    extract_bvid,
    get_cid,
    get_video_info,
    get_subtitle_url,
    download_subtitle_json,
)

from api.models import (
    AudioInfo,
    ErrorResponse,
    OutputFormat,
    ProgressInfo,
    ProgressPhase,
    SubtitleEntry,
    TaskProgress,
    TaskRequest,
    TaskStatus,
    TaskStatusResponse,
    TranscriptMode,
    TranscriptResult,
    TranscriptSource,
    TranscribeRequest,
    TranscribeResponse,
    UsageInfo,
    WhisperModel,
)
from api.queue import Task, queue
from api.storage import storage
from api.worker import worker

router = APIRouter(tags=["transcribe"])

# Whisper models that are fast enough for sync mode
SYNC_CAPABLE_MODELS = {WhisperModel.tiny, WhisperModel.base, WhisperModel.small}


def _generate_task_id(bvid: str) -> str:
    """Generate a unique task identifier.

    Format: YYYYMMDD_HHMMSS_BVID_shortuuid

    Args:
        bvid: The video BV ID to embed in the task ID.

    Returns:
        A unique task ID string.
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    short_uuid = uuid.uuid4().hex[:6]
    return f"{ts}_{bvid}_{short_uuid}"


def _build_subtitle_entries(subtitles: list[dict]) -> list[SubtitleEntry]:
    """Convert raw subtitle dictionaries to SubtitleEntry models.

    Handles both 'from' and 'from_' keys for compatibility.

    Args:
        subtitles: List of raw subtitle segment dicts.

    Returns:
        A list of SubtitleEntry model instances.
    """
    entries = []
    for item in subtitles:
        entries.append(SubtitleEntry(
            from_=item.get("from", item.get("from_", 0)),
            to=item.get("to", 0),
            content=item.get("content", "").strip(),
        ))
    return entries


def _build_full_text(subtitles: list[dict]) -> str:
    """Concatenate subtitle content into a single plain-text string.

    Args:
        subtitles: List of subtitle segment dicts with 'content' keys.

    Returns:
        A single string with each subtitle on a new line.
    """
    return "\n".join(item.get("content", "").strip() for item in subtitles if item.get("content"))


def _try_sync_transcribe(req: TranscribeRequest) -> TranscribeResponse | None:
    """Attempt to transcribe a video synchronously using subtitles only.

    If the video has CC or AI subtitles, the result is returned immediately.
    Returns None when no subtitles are available, signaling the caller to
    fall back to asynchronous Whisper transcription.

    Args:
        req: The transcription request.

    Returns:
        A TranscribeResponse with the subtitle result, or None if
        synchronous transcription is not possible.

    Raises:
        HTTPException: If the URL is invalid or the video is not found.
    """
    try:
        bvid = extract_bvid(req.url)
    except SystemExit:
        raise HTTPException(status_code=400, detail={
            "error": "invalid_url", "message": f"无法解析 URL: {req.url}",
        })

    video_info = get_video_info(bvid)
    if not video_info:
        raise HTTPException(status_code=404, detail={
            "error": "video_not_found", "message": f"视频不存在或已删除: {bvid}",
        })

    title = video_info.get("title", bvid)
    author = video_info.get("owner", {}).get("name", "")
    duration = video_info.get("duration", 0)

    try:
        cid, _, total_pages = get_cid(bvid, req.page)
    except SystemExit:
        raise HTTPException(status_code=400, detail={
            "error": "invalid_page", "message": f"分 P 序号 {req.page} 无效",
        })

    start_time = time.time()

    # Try subtitles
    if req.mode in (TranscriptMode.auto, TranscriptMode.subtitle):
        sub_list = get_subtitle_url(bvid, cid, req.cookie)
        if sub_list:
            cc_subs = [s for s in sub_list if not s.get("lan", "").startswith("ai")]
            ai_subs = [s for s in sub_list if s.get("lan", "").startswith("ai")]
            ordered = cc_subs + ai_subs

            for sub in ordered:
                try:
                    sub_data = download_subtitle_json(sub["subtitle_url"])
                    body = sub_data.get("body", [])
                    if body:
                        elapsed = time.time() - start_time
                        subtitles = _build_subtitle_entries(body)
                        full_text = _build_full_text(body)

                        result = TranscriptResult(
                            bvid=bvid,
                            title=title,
                            author=author,
                            duration=duration,
                            source=TranscriptSource.subtitle,
                            total_pages=total_pages,
                            current_page=req.page,
                            entries=len(subtitles),
                            subtitles=subtitles,
                            full_text=full_text,
                        )

                        usage = UsageInfo(
                            source=TranscriptSource.subtitle,
                            model="",
                            duration_seconds=round(elapsed, 2),
                        )

                        task_id = _generate_task_id(bvid)

                        return TranscribeResponse(
                            task_id=task_id,
                            status=TaskStatus.completed,
                            mode="sync",
                            result=result,
                            usage=usage,
                        )
                except Exception:
                    continue

    # No subtitles found — sync not possible
    return None


def _should_use_async(req: TranscribeRequest) -> bool:
    """Determine whether a request should be processed asynchronously.

    Async mode is used when:
    - mode is 'whisper' (forced Whisper)
    - model is medium or larger (too slow for sync)
    - webhook is provided (explicit async callback)
    - mode is 'both' (requires Whisper)

    Args:
        req: The transcription request.

    Returns:
        True if the request should be processed asynchronously.
    """
    # Explicit async mode
    if req.mode == TranscriptMode.whisper:
        return True

    # Large models must be async
    if req.model not in SYNC_CAPABLE_MODELS:
        return True

    # Webhook implies async
    if req.webhook:
        return True

    # Both mode with Whisper requirement
    if req.mode == TranscriptMode.both:
        return True

    # Auto mode: async if no subtitles (will fall back to Whisper)
    # But we don't know yet, so we return False and let the sync path
    # determine if it can handle it
    return False


@router.post("/transcribe", response_model=TranscribeResponse, status_code=status.HTTP_200_OK)
async def submit_transcribe(req: TranscribeRequest):
    """Submit a transcription task.

    For videos with subtitles: returns the result immediately (sync, 200).
    For videos requiring Whisper: enqueues the task and returns 202.

    Args:
        req: The transcription request body.

    Returns:
        TranscribeResponse with the result (sync) or task ID (async).

    Raises:
        HTTPException 400: If the URL is invalid.
        HTTPException 429: If the queue is full or duplicate BV.
    """
    # Validate URL by trying to extract BV ID
    try:
        bvid = extract_bvid(req.url)
    except SystemExit:
        raise HTTPException(status_code=400, detail={
            "error": "invalid_url", "message": f"无法解析 URL: {req.url}",
        })

    # Try sync path first
    if not _should_use_async(req):
        sync_result = _try_sync_transcribe(req)
        if sync_result is not None:
            return sync_result

    # Async path: enqueue task
    task_id = _generate_task_id(bvid)

    task = Task(
        task_id=task_id,
        url=req.url,
        mode=req.mode,
        model=req.model,
        language=req.language,
        page=req.page,
        output_format=req.output_format,
        cookie=req.cookie,
        webhook=req.webhook,
    )

    if not queue.enqueue(task):
        raise HTTPException(status_code=429, detail={
            "error": "rate_limited",
            "message": "队列已满或相同视频已有任务在处理中",
        })

    # Persist immediately
    storage.save(task)

    # Ensure worker is running
    if not worker.is_running:
        worker.start()

    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=TranscribeResponse(
            task_id=task_id,
            status=TaskStatus.pending,
            mode="async",
            links={"self": f"/api/v1/transcribe/{task_id}"},
        ).model_dump(mode="json"),
    )


@router.get("/transcribe/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """Get the status and result of a transcription task.

    Args:
        task_id: The unique identifier of the task.

    Returns:
        TaskStatusResponse with progress, result, and usage info.

    Raises:
        HTTPException 404: If the task does not exist.
    """
    task = queue.peek(task_id)

    # If not in memory, try loading from disk
    if task is None:
        task = storage.load(task_id)

    if task is None:
        raise HTTPException(status_code=404, detail={
            "error": "task_not_found", "message": f"任务不存在: {task_id}",
        })

    # Build progress
    progress = TaskProgress(
        phase=task.progress.phase,
        percent=task.progress.percent,
        message=task.progress.message,
        bytes_downloaded=task.progress.bytes_downloaded,
        bytes_total=task.progress.bytes_total,
    )

    # Build request summary
    request_info = TaskRequest(
        url=task.url,
        model=task.model.value if isinstance(task.model, WhisperModel) else task.model,
        output_format=task.output_format.value if isinstance(task.output_format, OutputFormat) else task.output_format,
    )

    # Build result if completed
    result = None
    usage = None
    if task.result:
        subtitles = task.result.get("subtitles", [])
        result = TranscriptResult(
            bvid=task.result.get("bvid", ""),
            title=task.result.get("title", ""),
            author=task.result.get("author", ""),
            duration=task.result.get("duration", 0),
            source=task.result.get("source", "subtitle"),
            total_pages=task.result.get("total_pages", 1),
            current_page=task.result.get("current_page", 0),
            entries=task.result.get("entries", 0),
            subtitles=_build_subtitle_entries(subtitles),
            full_text=task.result.get("full_text", ""),
        )

    if task.usage:
        usage = UsageInfo(**task.usage)

    return TaskStatusResponse(
        task_id=task.task_id,
        status=task.status,
        mode="async" if task.webhook else "sync",
        created_at=task.created_at,
        completed_at=task.completed_at,
        progress=progress,
        request=request_info,
        result=result,
        usage=usage,
    )