"""任务列表端点 — 列出所有任务，支持分页和过滤，以及队列管理操作。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from src.web.models import (
    ProgressPhase,
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
        summaries.append(
            TaskSummary(
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
            )
        )

    return TaskListResponse(
        total=total,
        limit=limit,
        offset=offset,
        tasks=summaries,
    )


@router.post("/tasks/{task_id}/retry", status_code=status.HTTP_200_OK)
async def retry_task(task_id: str):
    """重试失败任务，将其重置为 pending。

    参数：
        task_id: 要重试的任务的唯一标识符。

    返回：
        包含任务状态的消息。

    抛出：
        HTTPException 404: 如果任务不存在。
        HTTPException 409: 如果任务状态不是 failed。
    """
    task = queue.peek(task_id)
    if task is None:
        task = storage.load(task_id)
    if task is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "task_not_found", "message": f"任务不存在: {task_id}"},
        )

    if task.status != TaskStatus.failed:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "invalid_state",
                "message": f"只能重试失败的任务，当前状态: {task.status.value}",
            },
        )

    task.status = TaskStatus.pending
    task.error = None
    task.progress.phase = ProgressPhase.queued
    task.progress.percent = 0
    task.progress.message = "等待处理（重试）"
    task.started_at = None
    task.completed_at = None
    storage.save(task)

    return {"task_id": task_id, "status": "pending", "message": "任务已重置为等待处理"}


@router.delete("/tasks/{task_id}", status_code=status.HTTP_200_OK)
async def delete_task(task_id: str):
    """从队列中删除任务（内存和磁盘）。

    参数：
        task_id: 要删除的任务的唯一标识符。

    返回：
        确认消息。

    抛出：
        HTTPException 404: 如果任务不存在。
    """
    task = queue.peek(task_id)
    if task is None:
        task = storage.load(task_id)
    if task is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "task_not_found", "message": f"任务不存在: {task_id}"},
        )

    queue.remove(task_id)
    storage.delete(task_id)

    return {"task_id": task_id, "message": "任务已删除"}


@router.post("/tasks/{task_id}/cancel", status_code=status.HTTP_200_OK)
async def cancel_task(task_id: str):
    """取消处理中的任务，将其标记为 failed。

    参数：
        task_id: 要取消的任务的唯一标识符。

    返回：
        确认消息。

    抛出：
        HTTPException 404: 如果任务不存在。
        HTTPException 409: 如果任务状态不是 processing。
    """
    task = queue.peek(task_id)
    if task is None:
        task = storage.load(task_id)
    if task is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "task_not_found", "message": f"任务不存在: {task_id}"},
        )

    if task.status != TaskStatus.processing:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "invalid_state",
                "message": f"只能取消处理中的任务，当前状态: {task.status.value}",
            },
        )

    task.status = TaskStatus.failed
    task.error = "用户取消"
    task.progress.phase = ProgressPhase.failed
    task.progress.percent = 0
    task.progress.message = "任务已取消"
    storage.save(task)

    return {"task_id": task_id, "message": "任务已取消"}
