"""Bilibili 转录执行 — 三级降级策略编排层.

调用 bilibili.py 获取视频信息/字幕/音频流，
调用 transcriber.py 进行 Whisper 转录。
不包含队列逻辑，供 bili_queue.py 和 fetch_transcript.py 共用。
"""

import urllib.error
from datetime import datetime
from pathlib import Path

from src.core.bilibili import (
    download_audio,
    download_subtitle_json,
    extract_bvid,
    get_audio_url,
    get_cid,
    get_subtitle_url,
    get_video_info,
)
from src.core.transcriber import whisper_transcribe

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = PROJECT_ROOT / "out"

TIMEOUT = 6 * 3600  # 6 小时


# ---------------------------------------------------------------------------
# 转录执行
# ---------------------------------------------------------------------------
def run_transcription(url: str, model: str, task_id: str = "") -> dict:
    """执行完整转录流程（三级降级），返回结果字典.

    参数:
        url: B 站视频链接或 BV ID
        model: Whisper 模型大小 (tiny/base/small/medium/large-v3)
        task_id: 任务 ID（仅用于日志上下文）

    返回:
        {"success": True, "bv": "...", "title": "...", "srt": "...", "audio": "...", "lines": N}
        {"success": False, "error": "..."}
    """
    # 1. 解析 BV ID
    try:
        bvid = extract_bvid(url)
    except Exception as e:
        return {"success": False, "error": f"URL 解析失败: {e}"}

    # 2. 获取视频信息
    title = bvid
    duration = 0
    try:
        info = get_video_info(bvid)
        title = info.get("title", bvid)
        duration = info.get("duration", 0)
    except Exception:
        pass

    # 3. 创建安全文件名（BV号_标题，标题截断 100 字符）
    safe_title = title[:100].replace("/", "_").replace("\\", "_").replace(" ", "_")
    filename = f"{bvid}_{safe_title}"

    # 4. 创建视频专属目录 out/BV号_标题/
    video_dir = OUTPUT_DIR / filename
    video_dir.mkdir(parents=True, exist_ok=True)

    # 5. 保存链接信息
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    link_info = (
        f"视频链接: https://www.bilibili.com/video/{bvid}/\n"
        f"BV号: {bvid}\n"
        f"标题: {title}\n"
        f"时长: {duration}秒\n"
        f"转录模型: {model}\n"
        f"转录时间: {now}\n"
    )
    (video_dir / "视频链接.txt").write_text(link_info, encoding="utf-8")

    # 6. 执行转录（三级降级）
    audio_path = video_dir / "audio.m4s"

    # 获取 CID
    try:
        cid, _part_title, _total_pages = get_cid(bvid, 0)
    except Exception as e:
        return {"success": False, "error": f"获取 CID 失败: {e}"}

    subtitles = []

    # 第 1/2 级：CC/AI 字幕
    try:
        sub_list = get_subtitle_url(bvid, cid, "")
        if sub_list:
            cc_subs = [s for s in sub_list if not s.get("lan", "").startswith("ai")]
            ai_subs = [s for s in sub_list if s.get("lan", "").startswith("ai")]
            for sub in cc_subs + ai_subs:
                try:
                    sub_data = download_subtitle_json(sub["subtitle_url"])
                    body = sub_data.get("body", [])
                    if body:
                        subtitles = body
                        break
                except urllib.error.URLError:
                    continue
    except Exception:
        pass

    # 第 3 级：Whisper 降级
    if not subtitles:
        try:
            audio_url = get_audio_url(bvid, cid)
            if audio_url:
                referer = f"https://www.bilibili.com/video/{bvid}/"
                download_audio(audio_url, str(audio_path), referer)
                result = whisper_transcribe(str(audio_path), "zh", model)
                if result:
                    subtitles = result
        except Exception as e:
            return {"success": False, "error": f"Whisper 转录失败: {e}"}

    if not subtitles:
        return {"success": False, "error": "该视频没有可用字幕"}

    # 7. 写入 SRT 字幕（仅保留标准字幕格式）
    from src.core.transcriber import format_srt
    srt_path = video_dir / "字幕.srt"
    srt_path.write_text(format_srt(subtitles), encoding="utf-8")

    return {
        "success": True,
        "bv": bvid,
        "title": title,
        "srt": str(srt_path),
        "audio": str(audio_path) if audio_path.exists() else None,
        "lines": len(subtitles),
    }


