#!/usr/bin/env python3
"""Download audio for each video in out/ without re-transcribing."""

import os, re, sys, json, time
import urllib.request

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.bilibili.com",
}

def api_get(url: str) -> dict:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))

def get_cid(bvid: str) -> str:
    """Get first page cid for a video."""
    data = api_get(f"https://api.bilibili.com/x/player/pagelist?bvid={bvid}")
    if data.get("code") == 0 and data.get("data"):
        return str(data["data"][0]["cid"])
    return None

def get_audio_url(bvid: str, cid: str) -> str:
    """Get audio stream URL."""
    data = api_get(f"https://api.bilibili.com/x/player/playurl?bvid={bvid}&cid={cid}&fnval=16&qn=64")
    if data.get("code") != 0:
        return None
    audio_list = data.get("data", {}).get("dash", {}).get("audio", [])
    if audio_list:
        return audio_list[0].get("baseUrl")
    return None

def download_audio(url: str, output_path: str) -> bool:
    """Download audio from URL."""
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            total = int(resp.headers.get("content-length", 0))
            downloaded = 0
            chunk_size = 65536
            with open(output_path, "wb") as f:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
            return True
    except Exception as e:
        print(f"    ✗ 下载失败: {e}", file=sys.stderr)
        return False

def main():
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
        cid = get_cid(bvid)
        if not cid:
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