#!/usr/bin/env python3
"""迁移脚本 — 清理 out/ 旧格式文件，批量重新加入队列.

用法:
    python3 script/migrate_to_new_format.py          # 执行迁移
    python3 script/migrate_to_new_format.py --dry-run  # 预览操作
"""

import argparse
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_ROOT / "out"
OPERATIONS_LOG = Path.home() / ".queue" / "operations.log"


def log_operation(msg: str) -> None:
    """写入操作日志."""
    OPERATIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    with open(OPERATIONS_LOG, "a", encoding="utf-8") as f:
        f.write(f"{ts} {msg}\n")
    print(f"  {msg}")


def main() -> None:
    parser = argparse.ArgumentParser(description="迁移 out/ 旧格式到新格式")
    parser.add_argument("--dry-run", action="store_true", help="预览操作，不实际执行")
    args = parser.parse_args()
    dry_run = args.dry_run

    if dry_run:
        print("=== DRY RUN 模式，不会实际修改 ===\n")

    # 扫描所有视频目录
    dirs = sorted([d for d in OUT_DIR.iterdir() if d.is_dir()])
    if not dirs:
        print("out/ 下没有视频目录")
        return

    # 统计
    to_delete = {"书面文稿.txt": 0, "字幕.srt": 0, "适配分析.md": 0}
    to_rename = 0
    to_queue: list[str] = []

    for video_dir in dirs:
        bv_match = re.match(r"(BV[a-zA-Z0-9]+)", video_dir.name)
        if not bv_match:
            continue
        bvid = bv_match.group(1)

        # 删除旧文件
        for old_name in ["书面文稿.txt", "字幕.srt", "适配分析.md"]:
            old_path = video_dir / old_name
            if old_path.exists():
                if dry_run:
                    to_delete[old_name] += 1
                else:
                    old_path.unlink()
                    to_delete[old_name] += 1

        # 改名 视频链接.txt → 视频信息.txt
        old_link = video_dir / "视频链接.txt"
        new_info = video_dir / "视频信息.txt"
        if old_link.exists() and not new_info.exists():
            if dry_run:
                to_rename += 1
            else:
                old_link.rename(new_info)
                to_rename += 1

        # 收集 BV ID 用于重新入队
        to_queue.append(bvid)

    # 输出摘要
    print(f"\n共扫描 {len(dirs)} 个目录:")
    for name, count in to_delete.items():
        if count:
            print(f"  {'将' if dry_run else '已'}删除 {name}: {count} 个")
    if to_rename:
        print(f"  {'将' if dry_run else '已'}改名 视频链接.txt → 视频信息.txt: {to_rename} 个")
    print(f"  {'将' if dry_run else '已'}加入队列: {len(to_queue)} 个 (模型: base)")

    if dry_run:
        return

    # 写入操作日志
    delete_parts = [f"{k} x{v}" for k, v in to_delete.items() if v]
    if delete_parts:
        log_operation(f"[MIGRATE] 删除: {', '.join(delete_parts)}")
    if to_rename:
        log_operation(f"[MIGRATE] 改名: 视频链接.txt → 视频信息.txt x{to_rename}")

    # 批量加入队列
    script_path = PROJECT_ROOT / "src" / "cli" / "bili_queue.py"
    added = 0
    for bvid in to_queue:
        result = subprocess.run(
            [sys.executable, str(script_path), "add", bvid, "base"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            added += 1

    log_operation(f"[QUEUE] 批量添加 {added}/{len(to_queue)} 个任务到队列 (模型: base)")
    print(f"\n✓ 迁移完成: {added} 个任务已加入队列")


if __name__ == "__main__":
    main()