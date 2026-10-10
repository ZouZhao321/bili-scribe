#!/usr/bin/env bash
# 回归验证：sync-to-win 的「复制口径 == 校验口径」
#
# 背景：issue #35 —— 复制阶段只取顶层 *.json / *.log，校验阶段却递归比对全部文件，
# 导致 logs/ 或任务记录目录里混入任何其他文件时回传被误判为失败。
# 修复后仍有两类易回归边界：隐藏文件（find -name 会匹配、shell glob 不会）与子目录。
#
# 本脚本完全在 mktemp 沙箱内运行（HOME 也重定向），不触碰真实
# ~/.bilibili-api/tasks、仓库 out/ 与 logs/。
set -euo pipefail

cd "$(dirname "$0")/../.."
SCRIPT="$PWD/script/sync-to-win.sh"

SB="$(mktemp -d)"
trap 'rm -rf "$SB"' EXIT

mkdir -p "$SB/repo/script" "$SB/win" "$SB/home/.bilibili-api/tasks" "$SB/repo/logs/archive" "$SB/repo/out/BV1TEST_v"
cp "$SCRIPT" "$SB/repo/script/sync-to-win.sh"
(cd "$SB/repo" && git init -q .)

# 应被归档
printf 'transcript\n' >"$SB/repo/out/BV1TEST_v/transcript.txt"
printf 'log\n' >"$SB/repo/logs/run.log"
printf '{"task_id":"t1"}\n' >"$SB/home/.bilibili-api/tasks/t1.json"
# 不应被归档，且不得导致校验失败
printf 'stray\n' >"$SB/repo/logs/note.txt"
printf 'stray\n' >"$SB/repo/logs/dl2.sh"
printf 'nested\n' >"$SB/repo/logs/archive/old.log"
printf 'hidden\n' >"$SB/repo/logs/.hidden.log"
printf 'junk\n' >"$SB/home/.bilibili-api/tasks/README.txt"
printf 'hidden\n' >"$SB/home/.bilibili-api/tasks/.hidden.json"

set +e
(cd "$SB/repo" && HOME="$SB/home" bash script/sync-to-win.sh --win-root "$SB/win" >"$SB/run.log" 2>&1)
rc=$?
set -e

fail() {
	echo "✗ $1" >&2
	echo "--- 脚本输出 ---" >&2
	cat "$SB/run.log" >&2
	exit 1
}

[ "$rc" -eq 0 ] || fail "回传退出码应为 0，实际 $rc（口径不一致会误报失败）"

DATE="$(date +%F)"
DEST="$SB/win/out/$DATE"
for f in "BV1TEST_v/transcript.txt" "_logs/run.log" "_tasks/t1.json"; do
	[ -f "$DEST/$f" ] || fail "应归档的文件未落盘: $f"
done

# 不归档的东西必须留在 WSL 侧（校验失败时的安全阀语义）
for f in "$SB/repo/logs/note.txt" "$SB/repo/logs/dl2.sh" "$SB/repo/logs/.hidden.log" \
	"$SB/repo/logs/archive/old.log" "$SB/home/.bilibili-api/tasks/README.txt" \
	"$SB/home/.bilibili-api/tasks/.hidden.json"; do
	[ -e "$f" ] || fail "不应被清空的文件被删除了: ${f#"$SB/"}"
done

# 归档集合必须精确 —— 多一个都说明口径漂了
n_archived=$(find "$DEST" -type f | wc -l | tr -d ' ')
[ "$n_archived" -eq 3 ] || fail "归档文件数应为 3，实际 $n_archived"

# 清空阶段必须真的清掉应归档的那三棵树
[ -z "$(ls -A "$SB/repo/out")" ] || fail "out/ 未被清空"
[ -z "$(ls -A "$SB/home/.bilibili-api/tasks" -I 'README.txt' -I '.hidden.json')" ] ||
	fail "任务记录未被清空（应只留下非 *.json 文件）"

# 显式提示必须出现 —— 静默跳过正是本 issue 的病因
grep -q "不归档" "$SB/run.log" || fail "未显式提示不归档的文件"

echo "✅ sync-to-win 口径一致性回归通过（exit=0，归档 3 个文件，6 个 stray 保留并已提示）"
