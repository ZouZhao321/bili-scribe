#!/usr/bin/env bash
# WSL → Windows：转录产物 / 任务记录 / 运行日志 回传
#
# 工作流约定（见 AGENTS.md「WSL 运行 → 产物回传」）：
#   WSL 是运行工作区，跑完后把内容按日期归档到 Windows 侧 out/<日期>/，并清空 WSL 侧，
#   使 WSL 每次都是从零开始的一批任务。
#
# 用法（在 WSL 的仓库根目录执行）：
#   bash script/sync-to-win.sh [选项]
#
# 选项：
#   --date YYYY-MM-DD   归档目录名（默认今天）
#   --win-root PATH     Windows 侧项目根（默认 $BILI_SCRIBE_WIN_ROOT，再默认内置路径）
#   --dry-run           只打印将执行的动作，不写入也不删除
#   --keep              回传后保留 WSL 侧内容（默认清空）
#   -h, --help          显示帮助
#
# 归档结构：
#   <win-root>/out/<日期>/
#   ├── <BV号>_<标题>/           转录产物（继承 WSL out/ 下的目录）
#   ├── _tasks/*.json            任务执行记录
#   └── _logs/*.log              运行日志
set -euo pipefail

DEFAULT_WIN_ROOT="/mnt/c/Users/ZouZhao/Desktop/Project/bili-scribe"

WIN_ROOT="${BILI_SCRIBE_WIN_ROOT:-$DEFAULT_WIN_ROOT}"
DATE="$(date +%F)"
DRY_RUN=0
KEEP=0

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$REPO_ROOT" ]; then
  REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi

SRC_OUT="$REPO_ROOT/out"
SRC_TASKS="$HOME/.bilibili-api/tasks"
SRC_LOGS="$REPO_ROOT/logs"

usage() {
  sed -n '2,28p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit 0
}

while [ $# -gt 0 ]; do
  case "$1" in
    --date)     DATE="${2:?--date 需要一个 YYYY-MM-DD 参数}"; shift 2 ;;
    --win-root) WIN_ROOT="${2:?--win-root 需要路径}"; shift 2 ;;
    --dry-run)  DRY_RUN=1; shift ;;
    --keep)     KEEP=1; shift ;;
    -h|--help)  usage ;;
    *) echo "✗ 未知参数: $1（用 --help 查看用法）" >&2; exit 2 ;;
  esac
done

DEST="$WIN_ROOT/out/$DATE"

# ── 工具函数 ────────────────────────────────────────────────────────────────
count_files() { find "$1" -type f 2>/dev/null | wc -l | tr -d ' '; }

say()  { printf '%s\n' "$*"; }

do_mkdir() {
  if [ "$DRY_RUN" = 1 ]; then say "  [dry-run] mkdir -p $1"; else mkdir -p "$1"; fi
}

do_rsync() {
  # do_rsync <源目录> <目标目录> [额外 rsync 参数...]
  local src="$1" dst="$2"; shift 2
  if [ "$DRY_RUN" = 1 ]; then
    say "  [dry-run] rsync -a $* '$src/' '$dst/'  ($(count_files "$src") 个文件)"
  else
    rsync -a "$@" "$src/" "$dst/"
  fi
}

# ── 前置检查 ────────────────────────────────────────────────────────────────
say "═══ 回传 WSL → Windows ═══"
say "WSL 仓库:   $REPO_ROOT"
say "Windows 侧: $WIN_ROOT"
say "归档目录:   out/$DATE/"
say "模式:       $([ "$DRY_RUN" = 1 ] && echo 'dry-run（不写入）' || echo '实际写入')$([ "$KEEP" = 1 ] && echo ' + keep（不回删 WSL 侧）' || echo ' + 回传后清空 WSL 侧')"

if [ "$DRY_RUN" = 0 ] && [ ! -d "$WIN_ROOT" ]; then
  echo "✗ Windows 侧项目根不存在: $WIN_ROOT（用 --win-root 指定）" >&2
  exit 1
fi

has_payload=0
for d in "$SRC_OUT" "$SRC_TASKS" "$SRC_LOGS"; do
  [ -d "$d" ] && [ -n "$(ls -A "$d" 2>/dev/null)" ] && has_payload=1
done
if [ "$has_payload" = 0 ]; then
  say "⚠ WSL 侧没有任何可回传内容（out/、任务记录、logs/ 均为空）"
  exit 0
fi

# ── 1. 转录产物 out/ ────────────────────────────────────────────────────────
say ""
if [ -d "$SRC_OUT" ] && [ -n "$(ls -A "$SRC_OUT" 2>/dev/null)" ]; then
  n_src=$(count_files "$SRC_OUT")
  say "① 转录产物: $n_src 个文件"
  do_mkdir "$DEST"
  do_rsync "$SRC_OUT" "$DEST"
  OUT_OK=1
else
  say "① 转录产物: 无（跳过）"
  OUT_OK=0
fi

# ── 2. 任务记录 ~/.bilibili-api/tasks/*.json ────────────────────────────────
say ""
if compgen -G "$SRC_TASKS/*.json" > /dev/null; then
  n_tasks=$(find "$SRC_TASKS" -maxdepth 1 -name '*.json' | wc -l | tr -d ' ')
  say "② 任务记录: $n_tasks 个 JSON"
  do_mkdir "$DEST/_tasks"
  if [ "$DRY_RUN" = 1 ]; then
    say "  [dry-run] cp $n_tasks 个 *.json → $DEST/_tasks/"
  else
    cp -f "$SRC_TASKS"/*.json "$DEST/_tasks/"
  fi
  TASKS_OK=1
else
  say "② 任务记录: 无（跳过）"
  TASKS_OK=0
fi

# ── 3. 运行日志 logs/*.log ──────────────────────────────────────────────────
say ""
if compgen -G "$SRC_LOGS/*.log" > /dev/null; then
  n_logs=$(find "$SRC_LOGS" -maxdepth 1 -name '*.log' | wc -l | tr -d ' ')
  say "③ 运行日志: $n_logs 个文件"
  do_mkdir "$DEST/_logs"
  if [ "$DRY_RUN" = 1 ]; then
    say "  [dry-run] cp $n_logs 个 *.log → $DEST/_logs/"
  else
    cp -f "$SRC_LOGS"/*.log "$DEST/_logs/"
  fi
  LOGS_OK=1
else
  say "③ 运行日志: 无（跳过，约定写入 $SRC_LOGS/）"
  LOGS_OK=0
fi

# ── 4. 校验：目标侧文件数必须覆盖源侧 ────────────────────────────────────────
if [ "$DRY_RUN" = 0 ]; then
  say ""
  say "④ 校验"
  fail=0
  if [ "$OUT_OK" = 1 ]; then
    n_dst=$(count_files "$DEST")
    # 目标含 _tasks/_logs，产物部分按目录比对：目标数应 ≥ 源产物数
    if [ "$n_dst" -lt "$n_src" ]; then
      say "  ✗ 产物文件数不足: 源 $n_src → 目标 $n_dst"; fail=1
    else
      say "  ✓ 产物: 源 $n_src → 目标 out/$DATE/ 共 $n_dst 个文件"
    fi
  fi
  if [ "$TASKS_OK" = 1 ]; then
    n_dst_t=$(find "$DEST/_tasks" -maxdepth 1 -name '*.json' | wc -l | tr -d ' ')
    [ "$n_dst_t" = "$n_tasks" ] || { say "  ✗ 任务记录不一致: $n_tasks → $n_dst_t"; fail=1; }
  fi
  if [ "$LOGS_OK" = 1 ]; then
    n_dst_l=$(find "$DEST/_logs" -maxdepth 1 -name '*.log' | wc -l | tr -d ' ')
    [ "$n_dst_l" = "$n_logs" ] || { say "  ✗ 日志不一致: $n_logs → $n_dst_l"; fail=1; }
  fi
  if [ "$fail" = 1 ]; then
    echo "✗ 校验失败，**保留 WSL 侧内容不做清理**，请人工核对。" >&2
    exit 1
  fi
  say "  ✓ 任务记录/日志文件数一致"

  # ── 5. 清空 WSL 侧（使下次从零开始） ──────────────────────────────────────
  if [ "$KEEP" = 1 ]; then
    say ""
    say "⑤ --keep：保留 WSL 侧内容"
  else
    say ""
    say "⑤ 清空 WSL 侧"
    if [ "$OUT_OK" = 1 ]; then
      find "$SRC_OUT" -mindepth 1 -maxdepth 1 -exec rm -rf {} +; say "  ✓ 已清空 out/"
    fi
    if [ "$TASKS_OK" = 1 ]; then
      rm -f "$SRC_TASKS"/*.json; say "  ✓ 已清空任务记录"
    fi
    if [ "$LOGS_OK" = 1 ]; then
      rm -f "$SRC_LOGS"/*.log; say "  ✓ 已清空 logs/"
    fi
  fi
fi

say ""
if [ "$DRY_RUN" = 1 ]; then
  say "✔ dry-run 完成（未写入、未删除）"
else
  say "✔ 回传完成: $DEST"
fi
