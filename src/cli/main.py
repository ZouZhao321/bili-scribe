#!/usr/bin/env python3
"""bili-scribe — B站视频字幕提取 + Whisper 本地语音转录工具.

统一命令行入口，整合所有子命令：
  - transcribe: 转录单个视频
  - queue:      持久化队列管理
  - batch:      批量下载合集
  - serve:      启动 HTTP API 服务
  - info:       查询视频信息
  - version:    显示版本信息

用法:
    bili-scribe transcribe <url> [options]
    bili-scribe queue <subcommand> [args]
    bili-scribe batch <url> [options]
    bili-scribe serve [options]
    bili-scribe info <url> [options]
    bili-scribe version
"""

import argparse
import sys
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.bilibili import extract_bvid, get_collection_info, get_video_info  # noqa: E402
from src.core.runner import run_transcription  # noqa: E402

VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# 参数解析器构建
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """构建完整的参数解析器树."""
    parser = argparse.ArgumentParser(
        prog="bili-scribe",
        description="B站视频字幕提取 + Whisper 本地语音转录工具",
        add_help=False,
    )
    parser.add_argument("--help", "-h", action="store_true", help="显示帮助信息")
    sub = parser.add_subparsers(dest="command", help="可用命令")

    # -- transcribe -----------------------------------------------------------
    p_trans = sub.add_parser("transcribe", help="转录单个视频")
    p_trans.add_argument("url", help="B站视频链接或 BV 号")
    p_trans.add_argument(
        "-m",
        "--model",
        default="base",
        choices=["tiny", "base", "small", "medium", "large-v3"],
        help="Whisper 模型（默认: base）",
    )
    p_trans.add_argument(
        "-l",
        "--language",
        default="zh",
        help="Whisper 语言提示，如 zh/en/ja（默认: zh）",
    )
    p_trans.add_argument(
        "-p",
        "--page",
        type=int,
        default=0,
        help="分 P 序号（从 0 开始，默认: 0）",
    )
    p_trans.add_argument(
        "-f",
        "--format",
        choices=["text", "srt", "json"],
        default="text",
        help="输出格式（默认: text）",
    )
    p_trans.add_argument(
        "-w",
        "--force-whisper",
        action="store_true",
        help="强制使用 Whisper（跳过字幕）",
    )
    p_trans.add_argument(
        "-o",
        "--output",
        default="",
        help="输出目录（默认: ./out/）",
    )
    p_trans.add_argument(
        "-c",
        "--cookie",
        default="",
        help="B 站登录 Cookie",
    )
    p_trans.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="静默模式，只输出结果路径",
    )

    # -- queue ----------------------------------------------------------------
    p_queue = sub.add_parser("queue", help="管理持久化转录队列")
    qsub = p_queue.add_subparsers(dest="queue_cmd", help="队列操作")

    q_add = qsub.add_parser("add", help="添加任务到队列")
    q_add.add_argument("url", help="B站视频链接或 BV 号")
    q_add.add_argument(
        "model",
        nargs="?",
        default="base",
        choices=["tiny", "base", "small", "medium", "large-v3"],
        help="Whisper 模型（默认: base）",
    )

    qsub.add_parser("status", help="查看队列状态")
    qsub.add_parser("cron", help="定时处理队列（由 cron 调用）")

    q_list = qsub.add_parser("list", help="列出任务")
    q_list.add_argument(
        "status",
        nargs="?",
        default=None,
        choices=["pending", "running", "done", "failed"],
        help="按状态过滤",
    )

    q_retry = qsub.add_parser("retry", help="重试失败任务")
    q_retry.add_argument("task_id", help="任务 ID")

    q_remove = qsub.add_parser("remove", help="删除任务")
    q_remove.add_argument("task_id", help="任务 ID")

    qsub.add_parser("cancel", help="取消当前运行的任务")

    q_clear = qsub.add_parser("clear", help="清空队列")
    q_clear.add_argument(
        "target",
        nargs="?",
        default=None,
        choices=["pending", "failed"],
        help="清空指定类型（默认: 提示确认）",
    )

    qsub.add_parser("install-cron", help="安装 crontab 调度（每 10 分钟）")
    qsub.add_parser("uninstall-cron", help="卸载 crontab 调度")

    # -- batch ----------------------------------------------------------------
    p_batch = sub.add_parser("batch", help="批量下载合集内所有视频")
    p_batch.add_argument("url", help="合集内任意视频链接或 BV 号")
    p_batch.add_argument(
        "-m",
        "--model",
        default="base",
        choices=["tiny", "base", "small", "medium", "large-v3"],
        help="Whisper 模型（默认: base）",
    )
    p_batch.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="仅列出合集视频，不下载",
    )
    p_batch.add_argument(
        "-o",
        "--output",
        default="",
        help="输出目录（默认: ./out/）",
    )

    # -- serve ----------------------------------------------------------------
    p_serve = sub.add_parser("serve", help="启动 HTTP API 服务")
    p_serve.add_argument(
        "--host",
        default="0.0.0.0",  # noqa: S104
        help="监听地址（默认: 0.0.0.0）",
    )
    p_serve.add_argument(
        "-p",
        "--port",
        type=int,
        default=8000,
        help="监听端口（默认: 8000）",
    )
    p_serve.add_argument(
        "-w",
        "--workers",
        type=int,
        default=1,
        help="工作进程数（默认: 1）",
    )

    # -- info -----------------------------------------------------------------
    p_info = sub.add_parser("info", help="查询视频信息（不转录）")
    p_info.add_argument("url", help="B站视频链接或 BV 号")
    p_info.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="JSON 格式输出",
    )

    # -- version --------------------------------------------------------------
    sub.add_parser("version", help="显示版本信息")

    # -- transcript-to-srt ----------------------------------------------------
    p_srt = sub.add_parser("transcript-to-srt", help="将转录文稿转换为 SRT 字幕")
    p_srt.add_argument("input", help="转录文稿.txt 路径")
    p_srt.add_argument(
        "output",
        nargs="?",
        default="",
        help="输出 SRT 文件路径（默认: 与输入同目录，后缀 .srt）",
    )

    return parser


# ---------------------------------------------------------------------------
# 命令处理函数
# ---------------------------------------------------------------------------


def cmd_transcribe(args: argparse.Namespace) -> None:
    """处理 transcribe 子命令."""

    # 执行转录
    result = run_transcription(args.url, args.model)

    if not result["success"]:
        print(result["error"], file=sys.stderr)
        sys.exit(1)

    # 输出结果
    if args.format == "srt":
        srt_path = result.get("srt")
        if srt_path:
            text = Path(srt_path).read_text(encoding="utf-8")
            print(text)
    elif args.format == "json":
        import json

        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        # text 格式
        if args.quiet:
            print(result.get("srt", ""))
        else:
            print(f"✓ 转录完成: {result.get('title', '')}")
            print(f"  BV:       {result.get('bv', '')}")
            print(f"  SRT 字幕: {result.get('srt', '')}")
            audio = result.get("audio")
            if audio:
                print(f"  音频:     {audio}")
            print(f"  文稿行数: {result.get('lines', 0)}")


def cmd_transcript_to_srt(args: argparse.Namespace) -> None:
    """处理 transcript-to-srt 子命令."""
    import re

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"❌ 文件不存在: {input_path}", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output) if args.output else input_path.with_suffix(".srt")

    content = input_path.read_text(encoding="utf-8")

    # 解析格式: [说话人 A] [tiny] [0.82] HH:MM:SS,mmm - HH:MM:SS,mmm
    # 下一行是文本内容
    pattern = re.compile(r"^\[.+?\] \[.+?\] \[.+?\] (\d{2}:\d{2}:\d{2},\d{3}) - (\d{2}:\d{2}:\d{2},\d{3})$")

    lines = content.strip().split("\n")
    srt_lines = []
    index = 1

    for i, line in enumerate(lines):
        m = pattern.match(line)
        if m:
            from_ts = m.group(1)
            to_ts = m.group(2)
            # 下一行是文本
            text = lines[i + 1].strip() if i + 1 < len(lines) else ""
            srt_lines.append(f"{index}")
            srt_lines.append(f"{from_ts} --> {to_ts}")
            srt_lines.append(text)
            srt_lines.append("")
            index += 1

    output_path.write_text("\n".join(srt_lines), encoding="utf-8")
    print(f"✓ SRT 字幕已生成: {output_path}")
    print(f"  共 {index - 1} 条字幕")


def cmd_queue(args: argparse.Namespace) -> None:
    """处理 queue 子命令."""
    if not args.queue_cmd:
        print("用法: bili-scribe queue <subcommand> [args]")
        print("可用子命令: add, list, status, retry, remove, cancel, clear, cron, install-cron, uninstall-cron")
        sys.exit(1)

    # 导入 bili_queue 模块，将参数转发
    from src.cli.bili_queue import (
        cmd_add,
        cmd_cancel,
        cmd_clear,
        cmd_cron,
        cmd_install_cron,
        cmd_list,
        cmd_remove,
        cmd_retry,
        cmd_status,
        cmd_uninstall_cron,
    )

    cmd_map = {
        "add": cmd_add,
        "cron": cmd_cron,
        "status": cmd_status,
        "list": cmd_list,
        "retry": cmd_retry,
        "remove": cmd_remove,
        "cancel": cmd_cancel,
        "clear": cmd_clear,
        "install-cron": cmd_install_cron,
        "uninstall-cron": cmd_uninstall_cron,
    }

    handler = cmd_map.get(args.queue_cmd)
    if handler:
        handler(args)
    else:
        print(f"未知的 queue 子命令: {args.queue_cmd}")
        sys.exit(1)


def cmd_batch(args: argparse.Namespace) -> None:
    """处理 batch 子命令."""
    import time

    from src.core.bilibili import extract_bvid

    # 复用 download_collection.py 中的逻辑
    url = args.url
    model = args.model

    # 解析 BV ID
    print("=" * 60)
    print("🔍 正在解析视频信息...")
    print("=" * 60)
    try:
        bvid = extract_bvid(url)
    except Exception as e:  # noqa: BLE001
        print(f"❌ URL 解析失败: {e}")
        sys.exit(1)
    print(f"   BV ID: {bvid}")

    # 获取合集信息
    collection = get_collection_info(bvid)
    if not collection:
        print("\n❌ 该视频不属于任何合集，或无法获取合集信息。")
        sys.exit(1)

    print(f"\n📦 发现合集: {collection['title']}")
    print(f"📊 共 {collection['ep_count']} 个视频")
    print("-" * 60)

    videos = collection["videos"]
    for i, v in enumerate(videos, 1):
        print(f"  {i:2d}. {v['bvid']}  {v['title']}")

    if not videos:
        print("❌ 合集内没有视频")
        sys.exit(1)

    # dry-run
    if args.dry_run:
        print(f"\n📋 共 {len(videos)} 个视频（dry-run，不下载）")
        return

    # 开始批量下载
    print(f"\n{'=' * 60}")
    print("🚀 开始批量下载合集所有视频文稿...")
    print(f"   模型: {model}")
    print(f"{'=' * 60}")

    success = 0
    failed = 0

    for i, v in enumerate(videos, 1):
        bv = v["bvid"]
        title = v["title"]
        print(f"\n[{i}/{len(videos)}] ▶ {title}")
        print(f"   链接: https://www.bilibili.com/video/{bv}/")

        try:
            result = run_transcription(bv, model=model)
            if result["success"]:
                success += 1
                print(f"   ✅ 完成，文稿行数: {result.get('lines', 0)}")
            else:
                failed += 1
                print(f"   ❌ 失败: {result.get('error', '未知错误')}")
        except KeyboardInterrupt:
            print(f"\n\n⚠️  用户中断，已下载 {success}/{len(videos)} 个视频")
            sys.exit(1)
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"   ❌ 异常: {e}")

        if i < len(videos):
            time.sleep(1)

    print(f"\n{'=' * 60}")
    print("📊 下载完成汇总")
    print(f"{'=' * 60}")
    print(f"   合集: {collection['title']}")
    print(f"   模型: {model}")
    print(f"   总计: {len(videos)} 个视频")
    print(f"   ✅ 成功: {success}")
    if failed:
        print(f"   ❌ 失败: {failed}")
    print(f"{'=' * 60}")


def cmd_serve(args: argparse.Namespace) -> None:
    """处理 serve 子命令."""
    import uvicorn

    uvicorn.run(
        "src.web.server:app",
        host=args.host,
        port=args.port,
        workers=args.workers,
    )


def cmd_info(args: argparse.Namespace) -> None:
    """处理 info 子命令."""
    try:
        bvid = extract_bvid(args.url)
    except Exception as e:  # noqa: BLE001
        print(f"❌ URL 解析失败: {e}")
        sys.exit(1)

    info = get_video_info(bvid)
    if not info:
        print("❌ 获取视频信息失败")
        sys.exit(1)

    if args.json:
        import json

        print(json.dumps(info, ensure_ascii=False, indent=2))
    else:
        print(f"标题:   {info.get('title', '未知')}")
        print(f"BV:     {bvid}")
        print(f"作者:   {info.get('owner', {}).get('name', '未知')}")
        print(f"时长:   {info.get('duration', 0)} 秒")
        desc = info.get("desc", "")
        if desc:
            print(f"简介:   {desc[:200]}{'...' if len(desc) > 200 else ''}")
        print(f"分P数:  {info.get('videos', 1)}")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def main() -> None:
    """统一 CLI 入口."""
    parser = build_parser()
    args = parser.parse_args()

    # version 不依赖其他命令
    if args.command == "version":
        print(f"bili-scribe {VERSION}")
        return

    # help 或没有命令
    if not args.command or args.help:
        parser.print_help()
        return

    # 路由到对应处理函数
    cmd_map = {
        "transcribe": cmd_transcribe,
        "queue": cmd_queue,
        "batch": cmd_batch,
        "serve": cmd_serve,
        "info": cmd_info,
        "transcript-to-srt": cmd_transcript_to_srt,
    }

    handler = cmd_map.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
