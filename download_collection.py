#!/usr/bin/env python3
"""B站合集批量下载脚本 — 自动下载合集内所有视频的字幕/转录文稿.

用法:
    python3 download_collection.py <BV号或视频链接>
    python3 download_collection.py <--url URL>

示例:
    python3 download_collection.py BV12m4y1u7N5
    python3 download_collection.py "https://www.bilibili.com/video/BV12m4y1u7N5"
    python3 download_collection.py BV12m4y1u7N5 --model tiny    # 最快
    python3 download_collection.py BV12m4y1u7N5 --model large-v3  # 最准
    python3 download_collection.py BV12m4y1u7N5 --dry-run        # 仅列出

说明:
    从 B 站 API 获取视频所属合集 (ugc_season) 信息，
    然后逐个下载合集内所有视频的文稿（字幕优先，Whisper 降级）。
"""

import argparse
import sys
import time
from pathlib import Path

# 确保能找到项目模块
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.bilibili import api_get, extract_bvid, get_video_info
from src.core.runner import run_transcription


def get_collection_info(bvid: str) -> dict | None:
    """获取视频所属合集 (ugc_season) 信息.

    参数:
        bvid: 视频 BV ID

    返回:
        {
            "title": 合集标题,
            "cover": 封面图,
            "ep_count": 视频数,
            "videos": [
                {"bvid": "...", "title": "...", "aid": ...},
                ...
            ]
        }
        如果视频不属于任何合集则返回 None.
    """
    info = get_video_info(bvid)
    season = info.get("ugc_season")
    if not season:
        return None

    title = season.get("title", "未命名合集")
    cover = season.get("cover", "")
    ep_count = season.get("ep_count", 0)

    # 提取所有视频
    videos = []
    for section in season.get("sections", []):
        for ep in section.get("episodes", []):
            videos.append({
                "bvid": ep.get("bvid", ""),
                "title": ep.get("title", ""),
                "aid": ep.get("aid", 0),
                "cid": ep.get("cid", 0),
            })

    return {
        "title": title,
        "cover": cover,
        "ep_count": ep_count,
        "videos": videos,
    }


def main():
    parser = argparse.ArgumentParser(description="B站合集批量下载脚本")
    parser.add_argument("url", help="B站视频链接或BV号")
    parser.add_argument("--model", default="small",
                        choices=["tiny", "base", "small", "medium", "large-v3"],
                        help="Whisper 模型大小（默认: small）")
    parser.add_argument("--dry-run", action="store_true",
                        help="仅列出合集视频，不下载")
    args = parser.parse_args()

    url = args.url
    model = args.model

    # 1. 解析 BV ID
    print("=" * 60)
    print("🔍 正在解析视频信息...")
    print("=" * 60)
    try:
        bvid = extract_bvid(url)
    except Exception as e:
        print(f"❌ URL 解析失败: {e}")
        sys.exit(1)

    print(f"   BV ID: {bvid}")

    # 2. 获取合集信息
    collection = get_collection_info(bvid)
    if not collection:
        print(f"\n❌ 该视频不属于任何合集，或无法获取合集信息。")
        print(f"   提示: 可以直接用 bili_queue.py add <url> 下载单个视频。")
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

    # 3. 仅列出（dry-run）
    if args.dry_run:
        print(f"\n📋 共 {len(videos)} 个视频（dry-run，不下载）")
        return

    # 4. 确认下载
    print(f"\n{'=' * 60}")
    print(f"🚀 开始批量下载合集所有视频文稿...")
    print(f"   模型: {model}（tiny最快，base推荐，large-v3最准）")
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
                print(f"   ✅ 完成: {result.get('transcript', '')}")
                print(f"      带时间戳: {result.get('transcript_ts', '')}")
                print(f"      文稿行数: {result.get('lines', 0)}")
            else:
                failed += 1
                print(f"   ❌ 失败: {result.get('error', '未知错误')}")

        except KeyboardInterrupt:
            print(f"\n\n⚠️  用户中断，已下载 {success}/{len(videos)} 个视频")
            sys.exit(1)
        except Exception as e:
            failed += 1
            print(f"   ❌ 异常: {e}")

        # 视频间短暂停顿，避免请求过快
        if i < len(videos):
            time.sleep(1)

    # 4. 汇总
    print(f"\n{'=' * 60}")
    print(f"📊 下载完成汇总")
    print(f"{'=' * 60}")
    print(f"   合集: {collection['title']}")
    print(f"   模型: {model}")
    print(f"   总计: {len(videos)} 个视频")
    print(f"   ✅ 成功: {success}")
    if failed:
        print(f"   ❌ 失败: {failed}")
    print(f"   输出目录: {PROJECT_ROOT / 'out'}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()