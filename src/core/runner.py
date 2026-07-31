"""Bilibili 转录执行 — 三级降级策略编排层.

调用 bilibili.py 获取视频信息/字幕/音频流，
调用 transcriber.py 进行 Whisper 转录。
不包含队列逻辑，供 bili_queue.py 和 fetch_transcript.py 共用。
"""

import argparse
import sys
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
        {"success": True, "bv": "...", "title": "...", "transcript": "...", "audio": "...", "lines": N}
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

    # 3. 创建安全文件名
    safe_title = title[:20].replace("/", "_").replace(" ", "_")
    filename = f"{bvid}_{safe_title}" if not task_id else f"{task_id}_{safe_title}"

    # 4. 确保输出目录
    audio_dir = OUTPUT_DIR / "audio"
    transcript_dir = OUTPUT_DIR / "transcripts"
    audio_dir.mkdir(parents=True, exist_ok=True)
    transcript_dir.mkdir(parents=True, exist_ok=True)

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
    (transcript_dir / f"{filename}_link.txt").write_text(link_info, encoding="utf-8")

    # 6. 执行转录（三级降级）
    audio_path = audio_dir / f"{filename}.m4s"
    transcript_path = transcript_dir / f"{filename}.txt"

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

    # 7. 写入文稿
    lines = [item.get("content", "") for item in subtitles]
    transcript_path.write_text("\n".join(lines), encoding="utf-8")

    return {
        "success": True,
        "bv": bvid,
        "title": title,
        "transcript": str(transcript_path),
        "audio": str(audio_path) if audio_path.exists() else None,
        "lines": len(lines),
    }


# ---------------------------------------------------------------------------
# 兼容 CLI 入口（供 fetch_transcript.py / pyproject.toml 调用）
# ---------------------------------------------------------------------------
def cli_main():
    """命令行转录入口，与旧 main.py 接口兼容."""
    parser = argparse.ArgumentParser(description="获取 B 站视频字幕")
    parser.add_argument("url", help="B 站视频链接或 BV ID")
    parser.add_argument("--text-only", action="store_true", help="仅输出纯文本")
    parser.add_argument("--timestamps", action="store_true", help="包含时间戳")
    parser.add_argument("--page", type=int, default=0, help="分 P 序号（从 0 开始）")
    parser.add_argument("--whisper", action="store_true", help="强制使用 Whisper 降级")
    parser.add_argument("--cookie", default="", help="B 站登录 Cookie")
    parser.add_argument("--json", action="store_true", help="输出原始 JSON")
    parser.add_argument("--language", default="zh", help="Whisper 语言提示（默认: zh）")
    parser.add_argument("--model", default="small", help="Whisper 模型大小")
    parser.add_argument("--save-audio", default="", help="保存音频文件到指定路径")
    args = parser.parse_args()

    result = run_transcription(args.url, args.model)
    if not result["success"]:
        print(result["error"], file=sys.stderr)
        sys.exit(1)

    if args.text_only:
        transcript_path = result.get("transcript")
        if transcript_path:
            text = Path(transcript_path).read_text(encoding="utf-8")
            print(text)
    else:
        print(f"✓ 转录完成: {result.get('title', '')}")
        print(f"  文稿: {result.get('transcript', '')}")
        print(f"  音频: {result.get('audio', '无')}")
        print(f"  行数: {result.get('lines', 0)}")


if __name__ == "__main__":
    cli_main()
