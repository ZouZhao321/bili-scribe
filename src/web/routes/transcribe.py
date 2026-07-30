"""转录端点 — 提交转录任务和查询结果。"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status

from src.core.bilibili import (
    extract_bvid,
    get_cid,
    get_video_info,
    get_subtitle_url,
    download_subtitle_json,
)

from src.web.models import (
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
from src.web.queue import Task, queue
from src.web.storage import storage
from src.web.worker import worker

router = APIRouter(tags=["transcribe"])

# 足够快以支持同步模式的 Whisper 模型
SYNC_CAPABLE_MODELS = {WhisperModel.tiny, WhisperModel.base, WhisperModel.small}


def _generate_task_id(bvid: str) -> str:
    """生成唯一的任务标识符。

    格式: YYYYMMDD_HHMMSS_BVID_shortuuid

    参数：
        bvid: 要嵌入任务 ID 的视频 BV ID。

    返回：
        唯一的任务 ID 字符串。
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    short_uuid = uuid.uuid4().hex[:6]
    return f"{ts}_{bvid}_{short_uuid}"


def _build_subtitle_entries(subtitles: list[dict]) -> list[SubtitleEntry]:
    """将原始字幕字典转换为 SubtitleEntry 模型。

    兼容处理 'from' 和 'from_' 键。

    参数：
        subtitles: 原始字幕片段字典列表。

    返回：
        SubtitleEntry 模型实例列表。
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
    """将字幕内容拼接为单个纯文本字符串。

    参数：
        subtitles: 包含 'content' 键的字幕片段字典列表。

    返回：
        每个字幕占一行的单一字符串。
    """
    return "\n".join(item.get("content", "").strip() for item in subtitles if item.get("content"))


def _try_sync_transcribe(req: TranscribeRequest) -> TranscribeResponse | None:
    """尝试仅使用字幕同步转录视频。

    如果视频有 CC 或 AI 字幕，立即返回结果。
    没有可用字幕时返回 None，通知调用者降级到异步 Whisper 转录。

    参数：
        req: 转录请求。

    返回：
        包含字幕结果的 TranscribeResponse，或 None（同步转录不可用时）。

    抛出：
        HTTPException: 如果 URL 无效或视频未找到。
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

    # 尝试字幕
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

    # 未找到字幕 — 同步不可用
    return None


def _should_use_async(req: TranscribeRequest) -> bool:
    """判断请求是否应异步处理。

    异步模式用于以下情况：
    - mode 为 'whisper'（强制 Whisper）
    - 模型为 medium 或更大（同步太慢）
    - 提供了 webhook（显式异步回调）
    - mode 为 'both'（需要 Whisper）

    参数：
        req: 转录请求。

    返回：
        如果请求应异步处理则返回 True。
    """
    # 显式异步模式
    if req.mode == TranscriptMode.whisper:
        return True

    # 大模型必须异步
    if req.model not in SYNC_CAPABLE_MODELS:
        return True

    # Webhook 意味着异步
    if req.webhook:
        return True

    # Both 模式需要 Whisper
    if req.mode == TranscriptMode.both:
        return True

    # Auto 模式：如果没有字幕则异步（将降级到 Whisper）
    # 但此时还不知道，返回 False 让同步路径判断
    return False


@router.post("/transcribe", response_model=TranscribeResponse, status_code=status.HTTP_200_OK)
async def submit_transcribe(req: TranscribeRequest):
    """提交转录任务。

    有字幕的视频：立即返回结果（同步，200）。
    需要 Whisper 的视频：将任务入队并返回 202。

    参数：
        req: 转录请求体。

    返回：
        包含结果（同步）或任务 ID（异步）的 TranscribeResponse。

    抛出：
        HTTPException 400: 如果 URL 无效。
        HTTPException 429: 如果队列已满或重复 BV。
    """
    # 通过尝试提取 BV ID 来验证 URL
    try:
        bvid = extract_bvid(req.url)
    except SystemExit:
        raise HTTPException(status_code=400, detail={
            "error": "invalid_url", "message": f"无法解析 URL: {req.url}",
        })

    # 先尝试同步路径
    if not _should_use_async(req):
        sync_result = _try_sync_transcribe(req)
        if sync_result is not None:
            return sync_result

    # 异步路径：任务入队
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

    # 立即持久化
    storage.save(task)

    # 确保工作者在运行
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
    """获取转录任务的状态和结果。

    参数：
        task_id: 任务的唯一标识符。

    返回：
        包含进度、结果和使用信息的 TaskStatusResponse。

    抛出：
        HTTPException 404: 如果任务不存在。
    """
    task = queue.peek(task_id)

    # 如果不在内存中，尝试从磁盘加载
    if task is None:
        task = storage.load(task_id)

    if task is None:
        raise HTTPException(status_code=404, detail={
            "error": "task_not_found", "message": f"任务不存在: {task_id}",
        })

    # 构建进度
    progress = TaskProgress(
        phase=task.progress.phase,
        percent=task.progress.percent,
        message=task.progress.message,
        bytes_downloaded=task.progress.bytes_downloaded,
        bytes_total=task.progress.bytes_total,
    )

    # 构建请求摘要
    request_info = TaskRequest(
        url=task.url,
        model=task.model.value if isinstance(task.model, WhisperModel) else task.model,
        output_format=task.output_format.value if isinstance(task.output_format, OutputFormat) else task.output_format,
    )

    # 如果已完成，构建结果
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