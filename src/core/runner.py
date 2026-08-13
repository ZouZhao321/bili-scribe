"""Bilibili 转录执行 — 三级降级策略编排层.

调用 bilibili.py 获取视频信息/字幕/音频流，
调用 transcriber.py 进行 Whisper 转录。
不包含队列逻辑，供 bili_queue.py 和 fetch_transcript.py 共用。
"""

import math
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
    get_video_url,
)
from src.core.transcriber import format_transcript, format_srt, whisper_transcribe

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = PROJECT_ROOT / "out"

TIMEOUT = 6 * 3600  # 6 小时


def _write_video_info(video_dir: Path, bvid: str, title: str, info: dict) -> None:
    """写入视频信息文件（纯视频元数据，不含转录信息）."""
    duration = info.get("duration", 0)
    owner = info.get("owner", {})
    stat = info.get("stat", {})
    
    # 时长格式化
    h, m = divmod(duration, 3600)
    m, s = divmod(m, 60)
    dur_str = f"{duration}秒"
    if h > 0:
        dur_str += f" ({h}:{m:02d}:{s:02d})"
    else:
        dur_str += f" ({m}:{s:02d})"
    
    # 发布时间
    pubdate = info.get("pubdate", 0)
    pubdate_str = datetime.fromtimestamp(pubdate).strftime("%Y-%m-%d %H:%M:%S") if pubdate else "未知"
    
    # 播放量格式化
    def fmt_num(n: int) -> str:
        if n >= 10000:
            return f"{n/10000:.1f}万"
        return str(n)
    
    lines = [
        f"视频链接: https://www.bilibili.com/video/{bvid}/",
        f"BV号: {bvid}",
        f"AV号: AV{info.get('aid', '')}",
        f"标题: {title}",
        f"UP主: {owner.get('name', '未知')}",
        f"UP主UID: {owner.get('mid', '')}",
        f"发布时间: {pubdate_str}",
        f"时长: {dur_str}",
        f"分区: {info.get('tname', '')}",
        f"标签: {info.get('videos', '')}",
        f"简介: {info.get('desc', '')}",
        "",
        f"播放: {fmt_num(stat.get('view', 0))}",
        f"弹幕: {fmt_num(stat.get('danmaku', 0))}",
        f"评论: {fmt_num(stat.get('reply', 0))}",
        f"点赞: {fmt_num(stat.get('like', 0))}",
        f"硬币: {fmt_num(stat.get('coin', 0))}",
        f"收藏: {fmt_num(stat.get('favorite', 0))}",
        f"转发: {fmt_num(stat.get('share', 0))}",
    ]
    (video_dir / "视频信息.txt").write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# 转录执行
# ---------------------------------------------------------------------------
def run_transcription(
    url: str,
    model: str,
    task_id: str = "",
    mode: str = "auto",
    language: str = "zh",
    page: int = 0,
    cookie: str = "",
) -> dict:
    """执行完整转录流程（三级降级），返回结果字典.

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

    # 5. 保存视频信息（元数据 + 热度，不含转录信息）
    _write_video_info(video_dir, bvid, title, info)

    # 6. 执行转录（三级降级）
    audio_path = video_dir / "audio.m4s"

    # 获取 CID
    try:
        cid, _part_title, _total_pages = get_cid(bvid, page)
    except Exception as e:
        return {"success": False, "error": f"获取 CID 失败: {e}"}

    subtitles = []
    source = "whisper"  # 默认来源

    # 第 1/2 级：CC/AI 字幕（mode 不是 whisper 时尝试）
    if mode != "whisper":
        try:
            sub_list = get_subtitle_url(bvid, cid, cookie)
            if sub_list:
                cc_subs = [s for s in sub_list if not s.get("lan", "").startswith("ai")]
                ai_subs = [s for s in sub_list if s.get("lan", "").startswith("ai")]
                for sub in cc_subs + ai_subs:
                    try:
                        sub_data = download_subtitle_json(sub["subtitle_url"])
                        body = sub_data.get("body", [])
                        if body:
                            subtitles = body
                            source = "subtitle"
                            break
                    except urllib.error.URLError:
                        continue
        except Exception:
            pass

    # 第 3 级：Whisper 降级（mode 不是 subtitle 且字幕为空时，或 mode 为 both/whisper 时）
    need_whisper = mode in ("whisper", "both") or (mode == "auto" and not subtitles)
    if need_whisper:
        try:
            audio_url = get_audio_url(bvid, cid)
            if audio_url:
                # DASH 格式：直接下载音频流
                referer = f"https://www.bilibili.com/video/{bvid}/"
                download_audio(audio_url, str(audio_path), referer)
            else:
                # DASH 不可用，回退到 FLV 格式 → ffmpeg 提取音频
                video_url = get_video_url(bvid, cid)
                if video_url:
                    video_path = video_dir / "video.flv"
                    referer = f"https://www.bilibili.com/video/{bvid}/"
                    download_audio(video_url, str(video_path), referer)
                    if video_path.exists():
                        import subprocess
                        subprocess.run(
                            ["ffmpeg", "-y", "-i", str(video_path),
                             "-vn", "-acodec", "copy", "-f", "mp4", str(audio_path)],
                            check=True, capture_output=True,
                        )
                        video_path.unlink()  # 删除视频文件，保留音频
            if audio_path.exists():
                result = whisper_transcribe(str(audio_path), language, model)
                if result:
                    if mode == "both":
                        # both 模式：Whisper 结果追加到字幕后面
                        subtitles.extend(result)
                    else:
                        subtitles = result
                    source = "whisper"
        except Exception as e:
            return {"success": False, "error": f"Whisper 转录失败: {e}"}

    if not subtitles:
        return {"success": False, "error": "该视频没有可用字幕"}

    # 7. 写入文稿
    # 确保 CC/AI 字幕也包含置信度字段（默认 0.99）
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
        "bv": bvid,
        "title": title,
        "author": info.get("owner", {}).get("name", ""),
        "duration": duration,
        "source": source,
        "full_text": transcript_text,
        "subtitles": subtitles,
        "transcript": str(transcript_path),
        "audio": str(audio_path) if audio_path.exists() else None,
        "lines": len(subtitles),
        "avg_prob": round(math.exp(avg_conf), 2) if avg_conf else 0,
    }


