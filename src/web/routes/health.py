"""健康检查端点 — 返回队列状态和组件健康检查结果。"""

from __future__ import annotations

import os
import time
import urllib.error
import urllib.request

from fastapi import APIRouter

from src.web.models import HealthCheckItem, HealthChecks, HealthResponse
from src.web.queue import queue
from src.web.worker import worker

router = APIRouter(tags=["health"])

# 服务器启动时间
_start_time = time.time()


def _check_bilibili_api() -> HealthCheckItem:
    """检查 B 站 API 是否可达。

    发送 GET 请求到 B 站在线状态端点。

    返回：
        包含状态 'ok' 或 'error' 的 HealthCheckItem。
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
    except urllib.error.URLError as e:
        return HealthCheckItem(status="error", message=f"B站API不可达: {e!s}")


def _check_disk_space() -> HealthCheckItem:
    """检查存储目录是否有足够的磁盘空间。

    返回：
        包含状态 'ok' 或 'error' 的 HealthCheckItem。
        当可用空间低于 100MB 时触发错误。
    """
    try:
        check_path = os.path.expanduser("~/.bilibili-api")
        os.makedirs(check_path, exist_ok=True)
        stat = os.statvfs(check_path)
        free_gb = stat.f_bavail * stat.f_frsize / (1024**3)
        if free_gb < 0.1:
            return HealthCheckItem(status="error", message=f"磁盘空间不足: {free_gb:.1f}GB")
        return HealthCheckItem(status="ok", message=f"磁盘空间充足 ({free_gb:.1f}GB)")
    except OSError as e:
        return HealthCheckItem(status="error", message=f"磁盘检查失败: {e!s}")


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """返回服务健康状态和队列统计信息。

    检查队列工作者、磁盘空间和 B 站 API 可达性。
    所有组件健康时返回 HTTP 200，否则在响应体中包含错误详情。

    返回：
        包含组件状态和队列统计的 HealthResponse。
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

    # 检查是否有组件处于错误状态
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
