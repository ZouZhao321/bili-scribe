"""任务列表端点 — 列出所有任务，支持分页和过滤。"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from src.web.models import (
    OutputFormat,
    TaskListResponse,
    TaskProgress,
    TaskStatus,
    TaskSummary,
    WhisperModel,
)
from src.web.queue import queue
from src.web.storage import storage

router = APIRouter(tags=["tasks"])


@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks(
    status: str | None = Query(None, description="过滤: pending/processing/completed/failed"),
    limit: int = Query(20, ge=1, le=100, description="每页数量"),
    offset: int = Query(0, ge=0, description="分页偏移"),
):
    """列出所有转录任务，支持可选的状态过滤和分页。

    参数：
        status: 可选的任务状态过滤。
        limit: 每页最大任务数（1-100）。
        offset: 分页跳过的任务数。

    返回：
        包含总数和任务摘要的 TaskListResponse。
    """
    tasks, total = queue.list(status=status, limit=limit, offset=offset)

    summaries = []
    for task in tasks:
        summaries.append(TaskSummary(
            task_id=task.task_id,
            status=task.status,
            mode="async" if task.webhook else "sync",
            url=task.url,
            model=task.model.value if isinstance(task.model, WhisperModel) else str(task.model),
            created_at=task.created_at,
            completed_at=task.completed_at,
            progress=TaskProgress(
                phase=task.progress.phase,
                percent=task.progress.percent,
                message=task.progress.message,
            ),
        ))

    return TaskListResponse(
        total=total,
        limit=limit,
        offset=offset,
        tasks=summaries,
    )