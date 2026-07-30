#!/usr/bin/env python3
"""CLI tool — batch download audio for videos in the out/ directory.

Iterates over existing video directories under out/, extracts the BV ID,
and downloads the audio stream for each video that does not already have
an audio.m4s file. Intended for batch audio download without re-transcribing.
"""

import os
import re
import sys
import time

# Ensure project root is on sys.path so core/ can be found
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.core.transcriber import api_get, get_cid, get_audio_url, download_audio, HEADERS

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "out")
OUT_DIR = os.path.abspath(OUT_DIR)


def main():
    """Iterate over video directories and download missing audio files.

    Scans the out/ directory for video subdirectories, extracts BV IDs
    from directory names, and downloads audio.m4s for each video that
    does not already have one. Includes a 1-second rate-limit delay
    between requests.
    """
    # Get all directories
    dirs = sorted([d for d in os.listdir(OUT_DIR) if os.path.isdir(os.path.join(OUT_DIR, d))])

    total = len(dirs)
    success = 0
    skipped = 0
    failed = 0

    for i, dir_name in enumerate(dirs):
        dir_path = os.path.join(OUT_DIR, dir_name)

        # Check if audio already exists
        audio_path = os.path.join(dir_path, "audio.m4s")
        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
            size_mb = os.path.getsize(audio_path) / 1024 / 1024
            print(f"[{i+1}/{total}] ⏭ {dir_name} (已有音频 {size_mb:.1f}MB)")
            skipped += 1
            continue

        # Extract BV number
        m = re.match(r'(BV[a-zA-Z0-9]+)', dir_name)
        if not m:
            print(f"[{i+1}/{total}] ✗ {dir_name} (无法解析BV号)")
            failed += 1
            continue
        bvid = m.group(1)

        print(f"[{i+1}/{total}] ▶ {dir_name}", end="", flush=True)

        # Get CID
        try:
            cid, _, _ = get_cid(bvid)
        except SystemExit:
            print(f" ✗ 获取CID失败")
            failed += 1
            continue
        print(f" (CID: {cid})", end="", flush=True)

        # Get audio URL
        audio_url = get_audio_url(bvid, cid)
        if not audio_url:
            print(f" ✗ 获取音频URL失败")
            failed += 1
            continue

        # Download audio
        if download_audio(audio_url, audio_path):
            size_mb = os.path.getsize(audio_path) / 1024 / 1024
            print(f" ✓ {size_mb:.1f}MB")
            success += 1
        else:
            print(f" ✗ 下载失败")
            failed += 1

        # Rate limit
        time.sleep(1)

    print(f"\n=== 完成 ===")
    print(f"成功: {success}, 跳过: {skipped}, 失败: {failed}, 总计: {total}")


if __name__ == "__main__":
    main()