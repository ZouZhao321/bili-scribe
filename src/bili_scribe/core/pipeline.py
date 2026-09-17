"""统一转录编排 — 与媒体源解耦的转录管线.

输入任何实现 MediaSource 协议的源（B站视频 / 本地文件），
输出统一结构的结果字典。三级降级策略在此编排：
字幕优先（第 1/2 级）→ Whisper 转录（第 3 级）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from bili_scribe.core.transcriber import format_transcript, whisper_transcribe

# ---------------------------------------------------------------------------
# 路径与常量
# ---------------------------------------------------------------------------
# 仓库根（src/bili_scribe/core/pipeline.py → parents[0..3] = core/bili_scribe/src/仓库根）
PROJECT_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = PROJECT_ROOT / "out"


def _build_dir_name(source_id: str, title: str) -> str:
    """构建输出目录名：恒为 {源标识}_{安全标题}（与原 runner 行为一致）.

    参数:
        source_id: 源唯一标识（B站 BV 号 / 本地文件名）.
        title: 视频标题（截断 100 字符，替换路径分隔符）.

    返回:
        目录名，如 "BV1xx_demo"。

    注:
        本函数恒双段拼接；若源需要在特定场景使用单段目录名
        （如本地文件默认标题），应在 get_metadata() 中提供
        dir_name 键，pipeline 优先采用源提供的目录名。
    """
    safe_title = title[:100].replace("/", "_").replace("\\", "_").replace(" ", "_")
    return f"{source_id}_{safe_title}"


def transcribe_source(
    source,
    model: str,
    task_id: str = "",
    mode: str = "auto",
    language: str = "zh",
    out_dir: Path = OUTPUT_DIR,
) -> dict:
    """执行与源无关的完整转录流程（三级降级），返回结果字典.

    参数:
        source: 实现 MediaSource 协议的媒体源（B站/本地文件）.
        model: Whisper 模型大小 (tiny/base/small/medium/large-v3).
        task_id: 任务 ID（保留兼容签名，当前无日志用途；worker 传入但不消费）.
        mode: 转录模式 (auto/subtitle/whisper/both).
        language: Whisper 语言提示.
        out_dir: 输出根目录（默认仓库 out/）.

    返回:
        {"success": True, "bv": source_id, "source_id": "...", "title": "...",
         "author": "...", "duration": N, "source": "subtitle"|"whisper",
         "full_text": "...", "subtitles": [...], "lines": N}
        {"success": False, "error": "..."}
    """
    # 1. 元数据（源自身完成降级处理；异常时兜底默认值，保证恒返回结果字典）
    meta: dict = {}
    try:
        meta = source.get_metadata()
    except (Exception, SystemExit) as e:  # noqa: BLE001  # 源实现异常降级为默认元数据，不向上抛（含 SystemExit）
        print(f"[pipeline] 获取元数据失败，降级默认值: {e}", file=sys.stderr)
    title = meta.get("title") or source.source_id
    duration = meta.get("duration", 0)

    # 2. 创建输出目录，写入元数据文件
    # 目录名优先采用源提供的 dir_name（本地默认标题时单段），否则恒双段拼接
    video_dir = out_dir / (meta.get("dir_name") or _build_dir_name(source.source_id, title))
    video_dir.mkdir(parents=True, exist_ok=True)
    meta_lines = source.meta_lines()
    if meta_lines:
        (video_dir / "视频信息.txt").write_text("\n".join(meta_lines), encoding="utf-8")

    # 3. 字幕优先（三级降级第 1/2 级：CC/AI 字幕）
    subtitles: list[dict] = []
    src = "whisper"  # 来源标记，字幕命中时改为 subtitle
    if mode != "whisper":
        try:
            fetched = source.get_subtitles()
        except (Exception, SystemExit) as e:  # noqa: BLE001  # 源实现异常降级为无字幕，保证恒返回结果字典（含 SystemExit）
            print(f"[pipeline] 获取字幕失败，降级 Whisper: {e}", file=sys.stderr)
            fetched = []
        if fetched:
            subtitles = fetched
            src = "subtitle"

    # 4. Whisper 转录（第 3 级降级）
    need_whisper = mode in ("whisper", "both") or (mode == "auto" and not subtitles)
    audio_path: Path | None = None
    if need_whisper:
        try:
            audio_path = source.get_audio(video_dir / "audio.m4s")
            if audio_path and Path(audio_path).exists():
                result = whisper_transcribe(str(audio_path), language, model)
                if result:
                    if mode == "both":
                        # both 模式：Whisper 结果追加到字幕后面
                        subtitles.extend(result)
                    else:
                        subtitles = result
                    src = "whisper"
        except (Exception, SystemExit) as e:  # noqa: BLE001  # Whisper 转录失败转为任务失败返回（含 SystemExit）
            return {"success": False, "error": f"Whisper 转录失败: {e}"}

    if not subtitles:
        error = getattr(source, "get_error", lambda: "")()
        return {"success": False, "error": error or "该视频没有可用字幕"}

    # 5. 写入文稿
    # 确保字幕也包含置信度字段（默认 0.99）
    for s in subtitles:
        if "avg_logprob" not in s:
            s["avg_logprob"] = -0.01  # exp(-0.01) ≈ 0.99

    transcript_text = format_transcript(subtitles, model=model)
    transcript_path = video_dir / "转录文稿.txt"
    transcript_path.write_text(transcript_text, encoding="utf-8")

    # 计算平均置信度
    avg_conf = sum(s.get("avg_logprob", 0) for s in subtitles) / len(subtitles)

    return {
        "success": True,
        "bv": source.source_id,  # 兼容 worker/CLI 既有读取（B站为 BV 号）
        "source_id": source.source_id,
        "title": title,
        "author": meta.get("author", ""),
        "duration": duration,
        "source": src,
        "full_text": transcript_text,
        "subtitles": subtitles,
        "transcript": str(transcript_path),
        "audio": str(audio_path) if audio_path and Path(audio_path).exists() else None,
        "lines": len(subtitles),
        "avg_prob": round(math.exp(avg_conf), 2) if avg_conf else 0,
    }
