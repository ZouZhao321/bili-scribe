"""Tasks list endpoint — list all tasks with pagination and filtering."""

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
    """List all transcription tasks with optional status filter and pagination.

    Args:
        status: Optional filter by task status.
        limit: Maximum number of tasks per page (1-100).
        offset: Number of tasks to skip for pagination.

    Returns:
        TaskListResponse with total count and task summaries.
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