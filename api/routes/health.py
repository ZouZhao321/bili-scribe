"""Health check endpoint — returns queue status and component health."""

from __future__ import annotations

import os
import time
import urllib.request

from fastapi import APIRouter

from api.models import HealthCheckItem, HealthChecks, HealthResponse
from api.queue import queue
from api.worker import worker

router = APIRouter(tags=["health"])

# Server start time
_start_time = time.time()


def _check_bilibili_api() -> HealthCheckItem:
    """Check whether the Bilibili API is reachable.

    Sends a GET request to the Bilibili online status endpoint.

    Returns:
        A HealthCheckItem with status 'ok' or 'error'.
    """
    try:
        req = urllib.request.Request(
            "https://api.bilibili.com/x/web-interface/online",
            headers={"User-Agent": "Mozilla/5.0"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                return HealthCheckItem(status="ok", message="B站API可达")
        return HealthCheckItem(status="error", message=f"HTTP {resp.status}")
    except Exception as e:
        return HealthCheckItem(status="error", message=f"B站API不可达: {str(e)}")


def _check_disk_space() -> HealthCheckItem:
    """Check whether the storage directory has sufficient disk space.

    Returns:
        A HealthCheckItem with status 'ok' or 'error'.
        Triggers an error when free space drops below 100 MB.
    """
    try:
        # Check the storage directory or a reasonable fallback
        check_path = os.path.expanduser("~/.bilibili-api")
        os.makedirs(check_path, exist_ok=True)
        stat = os.statvfs(check_path)
        free_gb = stat.f_bavail * stat.f_frsize / (1024 ** 3)
        if free_gb < 0.1:
            return HealthCheckItem(status="error", message=f"磁盘空间不足: {free_gb:.1f}GB")
        return HealthCheckItem(status="ok", message=f"磁盘空间充足 ({free_gb:.1f}GB)")
    except Exception as e:
        return HealthCheckItem(status="error", message=f"磁盘检查失败: {str(e)}")


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Return the service health status and queue statistics.

    Checks the queue worker, disk space, and Bilibili API reachability.
    Returns HTTP 200 if all components are healthy, or embeds error
    details in the response body.

    Returns:
        HealthResponse with component statuses and queue stats.
    """
    stats = queue.stats()
    all_ok = True

    checks = HealthChecks(
        queue_worker=HealthCheckItem(
            status="ok" if worker.is_running else "error",
            message="队列工作者运行正常" if worker.is_running else "队列工作者未运行",
        ),
        disk_space=_check_disk_space(),
        bilibili_api=_check_bilibili_api(),
    )

    # Check if any component is in error
    if checks.queue_worker.status != "ok":
        all_ok = False
    if checks.disk_space.status != "ok":
        all_ok = False
    if checks.bilibili_api.status != "ok":
        all_ok = False

    uptime = time.time() - _start_time

    response = HealthResponse(
        status="ok" if all_ok else "error",
        uptime=round(uptime, 1),
        queue=stats,
        checks=checks,
    )

    return response