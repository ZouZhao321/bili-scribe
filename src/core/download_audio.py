#!/usr/bin/env python3
"""CLI 工具 — 批量下载 out/ 目录中视频的音频。

遍历 out/ 下的视频目录，提取 BV ID，
为每个尚无 audio.m4s 的视频下载音频流。
旨在无需重新转录的情况下批量下载音频。
"""

import os
import re
import sys
import time

# 确保项目根目录在 sys.path 中，以便找到 core/
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.core.bilibili import api_get, get_cid, get_audio_url, download_audio, HEADERS

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "out")
OUT_DIR = os.path.abspath(OUT_DIR)


def main():
    """遍历视频目录，下载缺失的音频文件。

    扫描 out/ 目录下的视频子目录，从目录名中提取 BV ID，
    为每个尚无 audio.m4s 的视频下载音频。
    请求之间包含 1 秒的速率限制延迟。
    """
    # 获取所有目录
    dirs = sorted([d for d in os.listdir(OUT_DIR) if os.path.isdir(os.path.join(OUT_DIR, d))])

    total = len(dirs)
    success = 0
    skipped = 0
    failed = 0

    for i, dir_name in enumerate(dirs):
        dir_path = os.path.join(OUT_DIR, dir_name)

        # 检查音频是否已存在
        audio_path = os.path.join(dir_path, "audio.m4s")
        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
            size_mb = os.path.getsize(audio_path) / 1024 / 1024
            print(f"[{i+1}/{total}] ⏭ {dir_name} (已有音频 {size_mb:.1f}MB)")
            skipped += 1
            continue

        # 提取 BV 号
        m = re.match(r'(BV[a-zA-Z0-9]+)', dir_name)
        if not m:
            print(f"[{i+1}/{total}] ✗ {dir_name} (无法解析BV号)")
            failed += 1
            continue
        bvid = m.group(1)

        print(f"[{i+1}/{total}] ▶ {dir_name}", end="", flush=True)

        # 获取 CID
        try:
            cid, _, _ = get_cid(bvid)
        except SystemExit:
            print(f" ✗ 获取CID失败")
            failed += 1
            continue
        print(f" (CID: {cid})", end="", flush=True)

        # 获取音频 URL
        audio_url = get_audio_url(bvid, cid)
        if not audio_url:
            print(f" ✗ 获取音频URL失败")
            failed += 1
            continue

        # 下载音频
        if download_audio(audio_url, audio_path):
            size_mb = os.path.getsize(audio_path) / 1024 / 1024
            print(f" ✓ {size_mb:.1f}MB")
            success += 1
        else:
            print(f" ✗ 下载失败")
            failed += 1

        # 速率限制
        time.sleep(1)

    print(f"\n=== 完成 ===")
    print(f"成功: {success}, 跳过: {skipped}, 失败: {failed}, 总计: {total}")


if __name__ == "__main__":
    main()