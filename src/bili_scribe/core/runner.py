"""Bilibili 转录执行 — 兼容入口（薄壳）.

原三级降级编排已迁移到 pipeline.py（统一编排）+ sources/（源抽象），
本模块保留 run_transcription() 兼容签名，供 worker / CLI 调用。
"""

from __future__ import annotations

from pathlib import Path

from bili_scribe.core.pipeline import transcribe_source
from bili_scribe.core.sources.bilibili import BilibiliSource

# 兼容旧引用（历史常量，下游可能 import）
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def run_transcription(
    url: str,
    model: str,
    task_id: str = "",
    mode: str = "auto",
    language: str = "zh",
    page: int = 0,
    cookie: str = "",
) -> dict:
    """执行完整转录流程（三级降级），返回结果字典（兼容入口）.

    B 站 URL → BilibiliSource → pipeline 统一编排。
    签名与行为保持与原 runner 一致，worker/CLI 无需改动。

    参数:
        url: B 站视频链接或 BV ID
        model: Whisper 模型大小 (tiny/base/small/medium/large-v3)
        task_id: 任务 ID（仅用于日志上下文）
        mode: 转录模式 (auto/subtitle/whisper/both)
        language: Whisper 语言提示
        page: 分 P 序号（0-indexed）
        cookie: B 站登录 Cookie

    返回:
        {"success": True, "bv": "...", "title": "...", "author": "...",
         "duration": N, "source": "subtitle"|"whisper",
         "full_text": "...", "subtitles": [...], "lines": N}
        {"success": False, "error": "..."}
    """
    try:
        source = BilibiliSource(url=url, page=page, cookie=cookie)
    except SystemExit as e:  # URL 解析失败转为任务失败返回，不向上抛
        return {"success": False, "error": f"URL 解析失败: {e}"}
    return transcribe_source(
        source,
        model=model,
        task_id=task_id,
        mode=mode,
        language=language,
    )
