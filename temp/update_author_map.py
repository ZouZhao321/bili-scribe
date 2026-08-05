#!/usr/bin/env python3
"""
通过 B 站 API 更新作者映射表。

扫描 out/ 和 library/作者/ 下所有视频目录，通过 B 站 API 获取 UP 主名，
更新 scripts/migrate_out_structure.py 中的 BVID_AUTHOR_MAP。

用法：
  python3 scripts/update_author_map.py          # dry-run 预览变化
  python3 scripts/update_author_map.py --apply   # 写入脚本
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = PROJECT_ROOT / "scripts" / "migrate_out_structure.py"
OUT_DIR = PROJECT_ROOT / "out"
AUTHOR_DIR = PROJECT_ROOT / "library" / "作者"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.bilibili.com",
}

API_DELAY = 0.5  # 请求间隔（秒），避免触发限流


def extract_bvid(dirname: str) -> str:
    """从目录名中提取 BVID（前 12 个字符）。"""
    return dirname[:12]


def get_bvid_list() -> set[str]:
    """扫描所有目录，收集所有 BVID。"""
    bvids = set()

    # 扫描 out/
    if OUT_DIR.exists():
        for d in OUT_DIR.iterdir():
            if d.is_dir() and not d.name.startswith("."):
                bvids.add(extract_bvid(d.name))

    # 扫描 library/作者/
    if AUTHOR_DIR.exists():
        for author_dir in AUTHOR_DIR.iterdir():
            if not author_dir.is_dir():
                continue
            for video_dir in author_dir.iterdir():
                if video_dir.is_dir():
                    bvids.add(extract_bvid(video_dir.name))

    return bvids


def get_owner_from_api(bvid: str) -> str | None:
    """通过 B 站 API 获取视频的 UP 主名。"""
    url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        owner = data.get("data", {}).get("owner", {})
        return owner.get("name")
    except Exception as e:
        print(f"    ⚠ {bvid} API 请求失败: {e}", file=sys.stderr)
        return None


def read_existing_map() -> dict[str, str]:
    """从 migrate_out_structure.py 读取现有的 BVID_AUTHOR_MAP。"""
    if not MIGRATE_SCRIPT.exists():
        return {}

    content = MIGRATE_SCRIPT.read_text(encoding="utf-8")

    # 查找 BVID_AUTHOR_MAP = { ... }
    pattern = r'BVID_AUTHOR_MAP\s*=\s*\{(.*?)\}'
    match = re.search(pattern, content, re.DOTALL)
    if not match:
        return {}

    map_text = match.group(1)
    existing = {}
    for line in map_text.split("\n"):
        m = re.match(r'\s*"(BV\w+)"\s*:\s*"([^"]*)"', line)
        if m:
            existing[m.group(1)] = m.group(2)

    return existing


def write_map_to_script(bvid_map: dict[str, str]) -> None:
    """将 BVID_AUTHOR_MAP 写回 migrate_out_structure.py。"""
    if not MIGRATE_SCRIPT.exists():
        print(f"❌ 脚本不存在: {MIGRATE_SCRIPT}", file=sys.stderr)
        sys.exit(1)

    content = MIGRATE_SCRIPT.read_text(encoding="utf-8")

    # 生成新的映射文本
    lines = ["BVID_AUTHOR_MAP = {"]
    for bvid in sorted(bvid_map.keys()):
        lines.append(f'    "{bvid}": "{bvid_map[bvid]}",')
    lines.append("}")

    new_map_text = "\n".join(lines)

    # 替换旧映射
    pattern = r'BVID_AUTHOR_MAP\s*=\s*\{(.*?)\}'
    new_content = re.sub(pattern, new_map_text, content, count=1, flags=re.DOTALL)

    if new_content == content:
        print("  ⚠ 未找到 BVID_AUTHOR_MAP 占位符，写入失败", file=sys.stderr)
        return

    MIGRATE_SCRIPT.write_text(new_content, encoding="utf-8")
    print(f"  ✅ 已更新: {MIGRATE_SCRIPT.relative_to(PROJECT_ROOT)}")


def main():
    dry_run = "--apply" not in sys.argv

    print("=" * 60)
    print("  扫描所有视频目录，获取 BVID 列表...")
    print("=" * 60)

    bvids = get_bvid_list()
    print(f"  共发现 {len(bvids)} 个唯一 BVID")

    existing_map = read_existing_map()
    print(f"  现有映射: {len(existing_map)} 条")
    print()

    # 找出需要查询的 BVID（不在现有映射中的）
    to_query = bvids - set(existing_map.keys())
    if not to_query:
        print("  ✅ 所有 BVID 已有映射，无需更新")
        return

    print(f"  需要查询 {len(to_query)} 个新 BVID...")
    print()

    new_entries = {}
    for i, bvid in enumerate(sorted(to_query), 1):
        print(f"  [{i}/{len(to_query)}] {bvid}...", end=" ", flush=True)
        owner = get_owner_from_api(bvid)
        if owner:
            print(f"→ {owner}")
            new_entries[bvid] = owner
        else:
            print("→ 失败")
        time.sleep(API_DELAY)

    if not new_entries:
        print("  ⚠ 没有成功获取到新的 UP 主信息")
        return

    print()
    print(f"  成功获取 {len(new_entries)} 个新 UP 主:")
    for bvid, owner in sorted(new_entries.items()):
        print(f"    {bvid} → {owner}")

    if dry_run:
        print()
        print("=" * 60)
        print("  DRY-RUN 模式 — 未写入")
        print("  使用 --apply 写入脚本")
        print("=" * 60)
        return

    # 合并并写入
    full_map = {**existing_map, **new_entries}
    write_map_to_script(full_map)
    print()
    print(f"  ✅ 更新完成！共 {len(full_map)} 条映射")


if __name__ == "__main__":
    main()