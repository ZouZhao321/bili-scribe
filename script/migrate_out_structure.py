#!/usr/bin/env python3
"""
将 out/ 下新转录的视频，按作者分类迁移到 library/，并创建系列/作品软连接。

结构：
  out/                     ← 下载目录（新转录输出到这里，平铺原始格式）
  library/                 ← 整理后的文库
  ├── 作者/              ← 物理存储
  │   ├── 徐善良/
  │   ├── 以筠/
  │   ├── 卖报小郎君/
  │   ├── 通用教程/       ← 无明确作者归属的归入此类
  │   └── ...
  ├── 系列/              ← 软连接（按主题聚合）
  ├── 作品/              ← 软连接（按被拆解的小说名聚合）
  └── 大纲               ← 保留（手动编辑的摘要文件）

用法：
  python3 scripts/migrate_out_structure.py          # dry-run 预览
  python3 scripts/migrate_out_structure.py --apply   # 执行迁移
  ├── 作者/              ← 物理存储（唯一真实位置）
  │   ├── 徐善良/
  │   ├── 以筠/
  │   ├── 卖报小郎君/
  │   ├── 通用教程/       ← 无明确作者归属的归入此类
  │   └── ...
  ├── 系列/              ← 软连接（按主题聚合）
  │   ├── 世界观设计/
  │   ├── 人设塑造/
  │   ├── 大纲细纲/
  │   └── ...
  ├── 作品/              ← 软连接（按被拆解的小说名聚合）
  │   ├── 大奉打更人/
  │   ├── 灵境行者/
  │   └── ...
  └── 大纲               ← 保留（手动编辑的摘要文件）

用法：
  python3 scripts/migrate_out_structure.py          # dry-run 预览
  python3 scripts/migrate_out_structure.py --apply   # 执行迁移
"""

import argparse
import os
import shutil
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_ROOT / "out"
LIBRARY_DIR = PROJECT_ROOT / "library"
AUTHOR_DIR = LIBRARY_DIR / "作者"
SERIES_DIR = LIBRARY_DIR / "系列"
WORK_DIR = LIBRARY_DIR / "作品"

# 需要排除的目录（不迁移）
EXCLUDE_DIRS = {"大纲"}

# 需要排除的目录（不迁移）
EXCLUDE_DIRS = {"大纲"}

# ---------------------------------------------------------------------------
# 作者匹配规则
# 格式: (关键词, 作者目录名)
# 按优先级从高到低排列
# ---------------------------------------------------------------------------
AUTHOR_RULES = [
    ("徐善良拆书", "徐善良"),
    ("徐善良", "徐善良"),
    ("卖报小郎君", "卖报小郎君"),
    ("白特慢啊", "白特慢啊"),
    ("96捞鱼费舍尔", "96捞鱼费舍尔"),
    ("【世界观设计", "以筠"),
    ("以筠", "以筠"),
    ("蜜汁姬", "蜜汁姬"),
    ("天蚕土豆", "天蚕土豆"),
    ("蜀中剑士", "蜀中剑士"),
    ("会说话的肘子", "会说话的肘子"),
    ("七月新番", "七月新番"),
    ("滚开", "滚开"),
]

# 特殊匹配：通过 BVID 精确匹配作者（当标题不包含关键词时）
BVID_AUTHOR_MAP = {
    "BV1ZQ316sE3Z": "滚开",  # 拆解滚开《十方武圣》
}

# 默认作者（无匹配时）
DEFAULT_AUTHOR = "通用教程"


# ---------------------------------------------------------------------------
# 系列映射
# 格式: BVID → [系列名列表]
# ---------------------------------------------------------------------------
SERIES_MAP: dict[str, list[str]] = {
    # === 世界观设计系列（以筠） ===
    "BV13SG36QEYH": ["世界观设计"],
    "BV1eLjy6ZEhH": ["世界观设计"],
    "BV1gbEB6kEEW": ["世界观设计"],
    "BV1HF9mBTEMf": ["世界观设计"],
    "BV1Hj7L6bE4u": ["世界观设计"],
    "BV1JuEP6tEt1": ["世界观设计"],
    "BV1uARCBkEma": ["世界观设计"],
    "BV1Um5h6rExp": ["世界观设计"],
    "BV1cDga6RER5": ["世界观设计"],
    # === 人设塑造系列 ===
    "BV1EWcVeZETx": ["人设塑造"],
    "BV1ewvFeNEco": ["人设塑造"],
    "BV1VwvFeKEMd": ["人设塑造"],
    "BV1YwvFeNEs8": ["人设塑造"],
    # === 大纲细纲系列 ===
    "BV1Gj411Y7rY": ["大纲细纲"],
    "BV1Fj411y71y": ["大纲细纲"],
    "BV1yg411h7zy": ["大纲细纲"],
    "BV1hLfdBdEC1": ["大纲细纲"],
    "BV1d34y1b7og": ["大纲细纲"],
    "BV1nYDWYKEc3": ["大纲细纲"],
    "BV1YuTG6gEN4": ["大纲细纲"],
    "BV1nbKP6hE45": ["大纲细纲"],
    # 大纲/ 目录下的 13 个视频（细纲专题）
    "BV11N41117iU": ["大纲细纲"],
    "BV11Z4y1H7ra": ["大纲细纲"],
    "BV12bKH6sE7c": ["大纲细纲"],
    "BV12L411i7km": ["大纲细纲"],
    "BV15N4y1H7vd": ["大纲细纲"],
    "BV1GnFyeMEPR": ["大纲细纲"],
    "BV1ma4y1J7tY": ["大纲细纲"],
    "BV1mFc1eeEmJ": ["大纲细纲"],
    "BV1op4y1g7UA": ["大纲细纲"],
    "BV1tE411f7wZ": ["大纲细纲"],
    "BV1TxJhzvEtx": ["大纲细纲"],
    "BV1X44y1k7H4": ["大纲细纲"],
    "BV1HC4y1V7ir": ["大纲细纲"],
    # === 网文困境系列 ===
    "BV17B4y1Z7Gk": ["网文困境"],
    "BV1AN411b76j": ["网文困境"],
    "BV1E8411k7Yp": ["网文困境"],
    # === 星河直播间（跨作者） ===
    "BV1a7wCeMETp": ["星河直播间"],
    "BV1bswFeCEGo": ["星河直播间"],
    "BV1LMwCe5E31": ["星河直播间"],
    "BV1Uw4m1k788": ["星河直播间"],
    # === 作者访谈系列 ===
    "BV13pKy6ZEuy": ["作者访谈"],
    "BV1cgMb6BEa9": ["作者访谈"],
    "BV1i5ML6tEQb": ["作者访谈"],
    "BV1dG411m7EL": ["作者访谈"],
    # === 拆书合集 ===
    "BV118411r7jt": ["拆书合集"],
    "BV11m4y137tn": ["拆书合集"],
    "BV12m4y1u7N5": ["拆书合集"],
    "BV16a4y1d7ZV": ["拆书合集"],
    "BV16Q4y1j7HJ": ["拆书合集"],
    "BV1Ae411z7pK": ["拆书合集"],
    "BV1Ak4y1N7if": ["拆书合集"],
    "BV1BRGg6bE25": ["拆书合集"],
    "BV1ch4y1N7KN": ["拆书合集"],
    "BV1cN411g72r": ["拆书合集"],
    "BV1cz4y1q73f": ["拆书合集"],
    "BV1D14y197ui": ["拆书合集"],
    "BV1eN411G7Wk": ["拆书合集"],
    "BV1EM411R7TJ": ["拆书合集"],
    "BV1fC4y1P7om": ["拆书合集"],
    "BV1Ku4y1476c": ["拆书合集"],
    "BV1MN4y1a73S": ["拆书合集"],
    "BV1nC4y177TW": ["拆书合集"],
    "BV1no4y1P7vN": ["拆书合集"],
    "BV1Pk4y1w7Ld": ["拆书合集"],
    "BV1QF411d7Z1": ["拆书合集"],
    "BV1qj41157Db": ["拆书合集"],
    "BV1rC4y1G7KS": ["拆书合集"],
    "BV1Rm4y1x7A4": ["拆书合集"],
    "BV1Su4y1Y7uL": ["拆书合集"],
    "BV1SV411P7Ey": ["拆书合集"],
    "BV1t34y1K7vB": ["拆书合集"],
    "BV1tpWgzDER9": ["拆书合集"],
    "BV1uVeSz4E4m": ["拆书合集"],
    "BV1vX4y1n7uP": ["拆书合集"],
    "BV1wt4215798": ["拆书合集"],
    "BV1Yz3d6VEbw": ["拆书合集"],
    "BV1ZQ316sE3Z": ["拆书合集"],
}

# ---------------------------------------------------------------------------
# 作品映射（按被拆解的小说名）
# 格式: BVID → [作品名列表]
# 一个视频可能涉及多部作品（如卖报小郎君同时聊大奉打更人和灵境行者）
# ---------------------------------------------------------------------------
WORK_MAP: dict[str, list[str]] = {
    "BV1cz4y1q73f": ["大奉打更人"],
    "BV1a7wCeMETp": ["大奉打更人"],
    "BV1bswFeCEGo": ["大奉打更人", "灵境行者"],
    "BV1LMwCe5E31": ["大奉打更人"],
    "BV1Rm4y1x7A4": ["灵境行者"],
    "BV1BRGg6bE25": ["谁让他修仙的！"],
    "BV1Yz3d6VEbw": ["谁让他修仙的！"],
    "BV16Q4y1j7HJ": ["仙父"],
    "BV1Pk4y1w7Ld": ["仙父"],
    "BV1cN411g72r": ["道爷要飞升"],
    "BV1Su4y1Y7uL": ["我在人间立地成仙"],
    "BV1qj41157Db": ["我在荒岛肝属性"],
    "BV1MN4y1a73S": ["无尽杀戮：我的火球有bug"],
    "BV16a4y1d7ZV": ["从搜山降魔开始"],
    "BV1Ae411z7pK": ["赤心巡天"],
    "BV1Ak4y1N7if": ["苟在妖武乱世修仙"],
    "BV1D14y197ui": ["盖世神医"],
    "BV1eN411G7Wk": ["明日拜堂"],
    "BV1EM411R7TJ": ["我不会武功，我只是天生神力"],
    "BV1ch4y1N7KN": ["我的超能力每周刷新"],
    "BV1rC4y1G7KS": ["我用闲书成圣人"],
    "BV1wt4215798": ["世子很凶"],
    "BV1vX4y1n7uP": ["历史架空题材"],
    "BV1Ku4y1476c": ["末日种田文"],
    "BV1uVeSz4E4m": ["夜无疆"],
    "BV1tpWgzDER9": ["阳神"],
    "BV1ZQ316sE3Z": ["十方武圣"],
    "BV1SV411P7Ey": ["怪谈游戏设计师"],
    "BV1t34y1K7vB": ["明克街13号"],
    "BV118411r7jt": ["择日飞升"],
    "BV11m4y137tn": ["我不是戏神"],
    "BV12m4y1u7N5": ["满堂华彩", "终宋"],
    "BV1no4y1P7vN": ["老白文（灵异玄幻向）"],
    "BV1QF411d7Z1": ["爆款网文拆解"],
    "BV19p421Z79g": ["十日终焉"],
    "BV1nC4y177TW": ["轻小说"],
    "BV1fC4y1P7om": ["爆款上榜网文"],
    "BV1SSw5eXExM": ["大奉打更人", "灵境行者"],
}

# ---------------------------------------------------------------------------
# 重复目录处理
# BV1jBgb6KEAg 有两个目录，保留内容更完整的，删除另一个
# ---------------------------------------------------------------------------
DUPLICATE_MERGE = {
    "BV1jBgb6KEAg": {
        "keep": "BV1jBgb6KEAg_为什么你写的角色不像活人？人物立体悲惨经历",
        "remove": "BV1jBgb6KEAg_角色不像活人",
    }
}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def extract_bvid(dirname: str) -> str:
    """从目录名中提取 BVID（前 12 个字符）。"""
    return dirname[:12]


def resolve_author(dirname: str) -> str:
    """根据目录名确定作者。"""
    bvid = extract_bvid(dirname)

    # 先检查 BVID 精确匹配
    if bvid in BVID_AUTHOR_MAP:
        return BVID_AUTHOR_MAP[bvid]

    # 再检查关键词匹配
    for keyword, author in AUTHOR_RULES:
        if keyword in dirname:
            return author

    return DEFAULT_AUTHOR


def get_series(dirname: str) -> list[str]:
    """获取视频所属的系列列表。"""
    bvid = extract_bvid(dirname)
    return SERIES_MAP.get(bvid, [])


def get_works(dirname: str) -> list[str]:
    """获取视频涉及的作品列表。"""
    bvid = extract_bvid(dirname)
    return WORK_MAP.get(bvid, [])


def create_symlink(target: Path, link: Path) -> None:
    """创建相对软连接，自动创建父目录。"""
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.exists() or link.is_symlink():
        link.unlink()
    # 计算相对路径
    rel_target = os.path.relpath(target, link.parent)
    link.symlink_to(rel_target)


# ---------------------------------------------------------------------------
# 主逻辑
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="迁移 out/ 目录结构：按作者分类 + 系列/作品软连接"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="执行迁移（默认是 dry-run 预览模式）",
    )
    args = parser.parse_args()

    dry_run = not args.apply

    if dry_run:
        print("=" * 60)
        print("  DRY-RUN 模式 — 仅预览，不执行任何操作")
        print("  使用 --apply 执行迁移")
        print("=" * 60)
        print()
    else:
        print("=" * 60)
        print("  执行迁移...")
        print("=" * 60)
        print()

    # -----------------------------------------------------------------------
    # 第一步：扫描并处理重复目录
    # -----------------------------------------------------------------------
    print("【第一步】处理重复目录...")
    for bvid, info in DUPLICATE_MERGE.items():
        keep_name = info["keep"]
        remove_name = info["remove"]
        keep_path = OUT_DIR / keep_name
        remove_path = OUT_DIR / remove_name

        if keep_path.exists() and remove_path.exists():
            print(f"  📦 发现重复: {bvid}")
            print(f"    保留: {keep_name}")
            print(f"    删除: {remove_name}")
            if not dry_run:
                shutil.rmtree(remove_path)
                print(f"    ✅ 已删除: {remove_name}")
        elif keep_path.exists():
            print(f"  ✓ {bvid} 已处理（只保留了一个目录）")
    print()

    # -----------------------------------------------------------------------
    # 第二步：扫描所有目录，建立迁移计划
    # -----------------------------------------------------------------------
    print("【第二步】扫描目录，建立迁移计划...")

    all_items = sorted(OUT_DIR.iterdir(), key=lambda p: p.name)
    moves = []  # [(源路径, 目标作者, 目标路径)]

    for item in all_items:
        if not item.is_dir():
            continue
        if item.name in EXCLUDE_DIRS:
            print(f"  ⏭ 跳过: {item.name}/（排除目录）")
            continue
        # 检查是否已经是新结构下的目录
        if item.name in ("作者", "系列", "作品"):
            print(f"  ⏭ 跳过: {item.name}/（新结构目录）")
            continue

        author = resolve_author(item.name)
        dest = AUTHOR_DIR / author / item.name
        moves.append((item, author, dest))

    # 统计
    author_counts: dict[str, int] = {}
    for _, author, _ in moves:
        author_counts[author] = author_counts.get(author, 0) + 1

    print(f"\n  共 {len(moves)} 个视频目录需要迁移")
    print(f"  涉及 {len(author_counts)} 个作者目录:")
    for author in sorted(author_counts.keys()):
        print(f"    {author}: {author_counts[author]} 个")
    print()

    # -----------------------------------------------------------------------
    # 第三步：执行迁移（移动目录）
    # -----------------------------------------------------------------------
    if moves:
        print("【第三步】迁移目录...")
        for src, author, dest in moves:
            if dry_run:
                print(f"  📦 {src.name}")
                print(f"     → {dest.relative_to(PROJECT_ROOT)}")
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dest))
                print(f"  ✅ {src.name}")
                print(f"     → {dest.relative_to(PROJECT_ROOT)}")
        print()
    else:
        print("【第三步】无需迁移。")
        print()

    if dry_run:
        print("=" * 60)
        print("  DRY-RUN 完成。使用 --apply 执行迁移。")
        print("=" * 60)
        return

    # -----------------------------------------------------------------------
    # 第四步：创建系列软连接
    # -----------------------------------------------------------------------
    print("【第四步】创建系列软连接...")

    series_count = 0
    for _, author, dest in moves:
        bvid = extract_bvid(dest.name)
        series_list = get_series(dest.name)
        for series_name in series_list:
            link_name = SERIES_DIR / series_name / dest.name
            create_symlink(dest, link_name)
            series_count += 1
            print(f"  🔗 {series_name}/{dest.name} → {dest.relative_to(PROJECT_ROOT)}")

    # 处理 library/大纲/ 目录下的视频（它们也在大纲细纲系列中）
    dagang_dir = LIBRARY_DIR / "大纲"
    if dagang_dir.exists():
        for item in dagang_dir.iterdir():
            if not item.is_dir():
                continue
            bvid = extract_bvid(item.name)
            series_list = get_series(item.name)
            for series_name in series_list:
                link_name = SERIES_DIR / series_name / item.name
                # 目标已经是新位置（在作者/通用教程/下）
                dest_in_author = AUTHOR_DIR / DEFAULT_AUTHOR / item.name
                if dest_in_author.exists():
                    create_symlink(dest_in_author, link_name)
                    series_count += 1

    print(f"  共创建 {series_count} 个系列软连接")
    print()

    # -----------------------------------------------------------------------
    # 第五步：创建作品软连接
    # -----------------------------------------------------------------------
    print("【第五步】创建作品软连接...")

    work_count = 0
    for _, author, dest in moves:
        works_list = get_works(dest.name)
        for work_name in works_list:
            link_name = WORK_DIR / work_name / dest.name
            create_symlink(dest, link_name)
            work_count += 1
            print(f"  🔗 {work_name}/{dest.name} → {dest.relative_to(PROJECT_ROOT)}")

    # 处理 library/大纲/ 目录下的视频，它们也可能有作品映射
    if dagang_dir.exists():
        for item in dagang_dir.iterdir():
            if not item.is_dir():
                continue
            works_list = get_works(item.name)
            for work_name in works_list:
                dest_in_author = AUTHOR_DIR / DEFAULT_AUTHOR / item.name
                if dest_in_author.exists():
                    link_name = WORK_DIR / work_name / item.name
                    create_symlink(dest_in_author, link_name)
                    work_count += 1

    print(f"  共创建 {work_count} 个作品软连接")
    print()

    # -----------------------------------------------------------------------
    # 第六步：处理 library/大纲/ 目录的剩余内容
    # -----------------------------------------------------------------------
    print("【第六步】处理 library/大纲/ 目录...")

    if dagang_dir.exists():
        # 将 library/大纲/ 下的视频目录移动到 作者/通用教程/
        dagang_videos = sorted(dagang_dir.iterdir())
        moved_count = 0
        for item in dagang_videos:
            if not item.is_dir():
                continue
            dest = AUTHOR_DIR / DEFAULT_AUTHOR / item.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                print(f"  ⚠ {item.name} 在通用教程中已存在，跳过")
                shutil.rmtree(item)
            else:
                shutil.move(str(item), str(dest))
                moved_count += 1
                print(f"  📦 {item.name} → 作者/通用教程/")

        # 保留摘要文件
        summary_file = dagang_dir / "细纲创作综合摘要.md"
        if summary_file.exists():
            dagang_series_dir = SERIES_DIR / "大纲细纲"
            dagang_series_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(summary_file), str(dagang_series_dir / "细纲创作综合摘要.md"))
            print(f"  📄 摘要文件已复制到 系列/大纲细纲/")

        remaining = list(dagang_dir.iterdir())
        if not remaining:
            dagang_dir.rmdir()
            print(f"  🗑 已删除空目录: library/大纲/")
        else:
            print(f"  ⚠ library/大纲/ 非空，剩余: {[p.name for p in remaining]}")

        print(f"  共迁移 {moved_count} 个视频")
    else:
        print(f"  ⏭ library/大纲/ 目录不存在，跳过")

    print()
    print("=" * 60)
    print("  ✅ 迁移完成！")
    print("=" * 60)
    print()
    print("最终结构:")
    print(f"  out/                     ← 下载目录（新转录）")
    print(f"  {LIBRARY_DIR.relative_to(PROJECT_ROOT)}/                 ← 整理后的文库")
    print(f"    ├── 作者/            ← 物理存储")
    print(f"    ├── 系列/            ← 软连接（按主题）")
    print(f"    ├── 作品/            ← 软连接（按作品）")
    print(f"    └── 大纲/            ← 细纲摘要")


if __name__ == "__main__":
    main()