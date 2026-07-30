"""CLI 入口 — 命令行转录流程编排。

调用 bilibili.py 获取视频信息/字幕/音频流，
调用 transcriber.py 进行 Whisper 转录。
"""
import argparse
import json
import os
import sys
import tempfile

from src.core.bilibili import (
    extract_bvid,
    get_cid,
    get_video_info,
    get_subtitle_url,
    download_subtitle_json,
    get_audio_url,
    download_audio,
)
from src.core.transcriber import whisper_transcribe, format_timestamp


def main():
    """从命令行参数运行转录流程。

    解析 CLI 参数，执行三级降级策略：
    CC 字幕 → AI 字幕 → Whisper 本地转录。
    """
    parser = argparse.ArgumentParser(description="获取 B 站视频字幕")
    parser.add_argument("url", help="B 站视频链接或 BV ID")
    parser.add_argument("--text-only", action="store_true", help="仅输出纯文本")
    parser.add_argument("--timestamps", action="store_true", help="包含时间戳")
    parser.add_argument("--page", type=int, default=0, help="分 P 序号（从 0 开始）")
    parser.add_argument("--whisper", action="store_true", help="强制使用 Whisper 降级")
    parser.add_argument("--cookie", default="", help="B 站登录 Cookie（用于需要登录的视频）")
    parser.add_argument("--json", action="store_true", help="输出原始 JSON")
    parser.add_argument("--language", default="zh", help="Whisper 语言提示（默认: zh）")
    parser.add_argument("--model", default="small", help="Whisper 模型大小: tiny/base/small/medium/large-v3（默认: small）")
    parser.add_argument("--save-audio", default="", help="保存音频文件到指定路径")
    args = parser.parse_args()

    # 提取 BV ID
    bvid = extract_bvid(args.url)
    print(f"视频: {bvid}", file=sys.stderr)

    # 获取视频信息
    video_info = get_video_info(bvid)
    title = video_info.get("title", bvid)
    duration = video_info.get("duration", 0)
    print(f"标题: {title}", file=sys.stderr)
    if duration:
        print(f"时长: {format_timestamp(duration)}", file=sys.stderr)

    # 获取 CID
    cid, part_title, total_pages = get_cid(bvid, args.page)
    if total_pages > 1:
        print(f"分 P: {args.page + 1}/{total_pages} - {part_title}", file=sys.stderr)

    subtitles = []
    source = "none"

    # 第 1/2 级：尝试从 API 获取 CC/AI 字幕
    if not args.whisper:
        sub_list = get_subtitle_url(bvid, cid, args.cookie)
        if sub_list:
            cc_subs = [s for s in sub_list if not s.get("lan", "").startswith("ai")]
            ai_subs = [s for s in sub_list if s.get("lan", "").startswith("ai")]
            ordered = cc_subs + ai_subs

            for sub in ordered:
                lang = sub.get("lan_doc", sub.get("lan", "unknown"))
                print(f"发现字幕: {lang}", file=sys.stderr)
                try:
                    sub_data = download_subtitle_json(sub["subtitle_url"])
                    body = sub_data.get("body", [])
                    if body:
                        subtitles = body
                        source = "cc" if not sub.get("lan", "").startswith("ai") else "ai"
                        print(f"使用: {source} 字幕 ({len(subtitles)} 条)", file=sys.stderr)
                        break
                except Exception as e:
                    print(f"下载字幕失败: {e}", file=sys.stderr)
                    continue
        else:
            print("未找到 CC/AI 字幕，降级到 Whisper...", file=sys.stderr)

    # 第 3 级：Whisper 降级
    if not subtitles:
        if not args.whisper and source == "none":
            print("自动启用 Whisper 转录...", file=sys.stderr)

        referer = f"https://www.bilibili.com/video/{bvid}/"
        audio_url = get_audio_url(bvid, cid)

        if not audio_url:
            print("错误: 无法获取音频流 URL", file=sys.stderr)
            sys.exit(1)

        with tempfile.NamedTemporaryFile(suffix=".m4s", delete=False) as tmp:
            audio_path = tmp.name

        try:
            print("正在下载音频流...", file=sys.stderr)
            if download_audio(audio_url, audio_path, referer):
                if args.save_audio:
                    import shutil
                    shutil.copy2(audio_path, args.save_audio)
                    print(f"音频已保存到: {args.save_audio}", file=sys.stderr)

                subtitles = whisper_transcribe(audio_path, args.language, args.model)
                if subtitles:
                    source = "whisper"
                    print(f"Whisper: {len(subtitles)} 个片段", file=sys.stderr)
        finally:
            try:
                os.unlink(audio_path)
            except OSError:
                pass

    if not subtitles:
        print("错误: 该视频没有可用字幕。", file=sys.stderr)
        sys.exit(1)

    # 输出
    if args.json:
        output = {
            "bvid": bvid,
            "title": title,
            "duration": duration,
            "source": source,
            "total_pages": total_pages,
            "current_page": args.page,
            "entries": len(subtitles),
            "subtitles": subtitles,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif args.text_only:
        print(f"# {title}\n")
        for item in subtitles:
            print(item.get("content", ""))
    elif args.timestamps:
        print(f"# {title}\n")
        for item in subtitles:
            ts = format_timestamp(item.get("from", 0))
            print(f"[{ts}] {item.get('content', '')}")
    else:
        print(f"# {title}")
        print(f"# 来源: {source}\n")
        for item in subtitles:
            print(item.get("content", ""))


if __name__ == "__main__":
    main()