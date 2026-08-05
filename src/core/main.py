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
    """Run the transcription pipeline from command-line arguments.

    Parses CLI arguments, then executes the three-tier fallback:
    CC subtitles → AI subtitles → Whisper local transcription.
    """
    parser = argparse.ArgumentParser(description="Fetch Bilibili video transcripts")
    parser.add_argument("url", help="Bilibili video URL or BV ID")
    parser.add_argument("--text-only", action="store_true", help="Output plain text only")
    parser.add_argument("--timestamps", action="store_true", help="Include timestamps")
    parser.add_argument("--page", type=int, default=0, help="Page/P number (0-indexed)")
    parser.add_argument("--whisper", action="store_true", help="Force Whisper fallback")
    parser.add_argument("--cookie", default="", help="Bilibili cookie for login-required videos")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    parser.add_argument("--language", default="zh", help="Whisper language hint (default: zh)")
    parser.add_argument("--model", default="small", help="Whisper model size: tiny/base/small/medium/large-v3 (default: small)")
    parser.add_argument("--save-audio", default="", help="Save audio file to this path")
    args = parser.parse_args()

    # Extract BV ID
    bvid = extract_bvid(args.url)
    print(f"Video: {bvid}", file=sys.stderr)

    # Get video info
    video_info = get_video_info(bvid)
    title = video_info.get("title", bvid)
    duration = video_info.get("duration", 0)
    print(f"Title: {title}", file=sys.stderr)
    if duration:
        print(f"Duration: {format_timestamp(duration)}", file=sys.stderr)

    # Get CID
    cid, part_title, total_pages = get_cid(bvid, args.page)
    if total_pages > 1:
        print(f"Page: {args.page + 1}/{total_pages} - {part_title}", file=sys.stderr)

    subtitles = []
    source = "none"

    # Tier 1 & 2: Try CC/AI subtitles from API
    if not args.whisper:
        sub_list = get_subtitle_url(bvid, cid, args.cookie)
        if sub_list:
            cc_subs = [s for s in sub_list if not s.get("lan", "").startswith("ai")]
            ai_subs = [s for s in sub_list if s.get("lan", "").startswith("ai")]
            ordered = cc_subs + ai_subs

            for sub in ordered:
                lang = sub.get("lan_doc", sub.get("lan", "unknown"))
                print(f"Found subtitle: {lang}", file=sys.stderr)
                try:
                    sub_data = download_subtitle_json(sub["subtitle_url"])
                    body = sub_data.get("body", [])
                    if body:
                        subtitles = body
                        source = "cc" if not sub.get("lan", "").startswith("ai") else "ai"
                        print(f"Using: {source} subtitles ({len(subtitles)} entries)", file=sys.stderr)
                        break
                except Exception as e:
                    print(f"Failed to download subtitle: {e}", file=sys.stderr)
                    continue
        else:
            print("No CC/AI subtitles found, falling back to Whisper...", file=sys.stderr)

    # Tier 3: Whisper fallback
    if not subtitles:
        if not args.whisper and source == "none":
            print("Auto-enabling Whisper transcription...", file=sys.stderr)

        referer = f"https://www.bilibili.com/video/{bvid}/"
        audio_url = get_audio_url(bvid, cid)

        if not audio_url:
            print("Error: cannot get audio stream URL", file=sys.stderr)
            sys.exit(1)

        with tempfile.NamedTemporaryFile(suffix=".m4s", delete=False) as tmp:
            audio_path = tmp.name

        try:
            print("Downloading audio stream...", file=sys.stderr)
            if download_audio(audio_url, audio_path, referer):
                if args.save_audio:
                    import shutil
                    shutil.copy2(audio_path, args.save_audio)
                    print(f"Audio saved to: {args.save_audio}", file=sys.stderr)

                subtitles = whisper_transcribe(audio_path, args.language, args.model)
                if subtitles:
                    source = "whisper"
                    print(f"Whisper: {len(subtitles)} segments", file=sys.stderr)
        finally:
            try:
                os.unlink(audio_path)
            except OSError:
                pass

    if not subtitles:
        print("Error: No subtitles available for this video.", file=sys.stderr)
        sys.exit(1)

    # Output
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
        print(f"# Source: {source}\n")
        for item in subtitles:
            print(item.get("content", ""))


if __name__ == "__main__":
    main()