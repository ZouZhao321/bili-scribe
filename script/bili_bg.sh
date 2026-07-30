#!/bin/bash
# Bilibili video transcript - background queue mode
# Runs transcription in background, auto-queues if another is running
#
# Usage: ./bili_bg.sh "URL1" "URL2" ... [model]
#        ./bili_bg.sh "URL" small
#        ./bili_bg.sh urls.txt         # 从文件读取URL列表
#
# Status: ./bili_bg.sh --status
#         ./bili_bg.sh --log <task_id>

SCRIPT_DIR="$(cd "$(dirname "$0")" && cd .. && pwd)"
shopt -s nullglob
QUEUE_DIR="$HOME/bilibili-output/.queue"
LOCK_FILE="$QUEUE_DIR/queue.lock"
LOG_DIR="$QUEUE_DIR/logs"

mkdir -p "$QUEUE_DIR" "$LOG_DIR"

# 显示状态
if [ "$1" = "--status" ]; then
	echo "=== 队列状态 ==="
	echo ""

	# 正在运行的任务
	if [ -f "$LOCK_FILE" ]; then
		RUNNING=$(cat "$LOCK_FILE")
		echo "▶ 正在运行: $RUNNING"
		echo "  日志: $(ls -t "$LOG_DIR" 2>/dev/null | head -1)"
		echo ""
	else
		echo "▶ 当前无运行中的任务"
		echo ""
	fi

	# 已完成的任务
	echo "=== 已完成 ==="
	if [ -d "$LOG_DIR" ]; then
		for log in "$LOG_DIR"/*.done; do
			[ -f "$log" ] || continue
			name=$(basename "$log" .done)
			echo "  ✓ $name"
		done
	fi
	echo ""

	# 失败的任务
	echo "=== 失败 ==="
	if [ -d "$LOG_DIR" ]; then
		for log in "$LOG_DIR"/*.fail; do
			[ -f "$log" ] || continue
			name=$(basename "$log" .fail)
			echo "  ✗ $name"
		done
	fi
	fail_files=("$LOG_DIR"/*.fail)
	[ ${#fail_files[@]} -eq 0 ] && echo "  （无）"

	exit 0
fi

# 查看日志
if [ "$1" = "--log" ] && [ -n "$2" ]; then
	LOG_FILE="$LOG_DIR/$2.log"
	if [ -f "$LOG_FILE" ]; then
		cat "$LOG_FILE"
	else
		echo "日志不存在: $2"
		echo "可用日志:"
		ls "$LOG_DIR"/*.log 2>/dev/null | sed 's/.*\///' | sed 's/\.log$//'
	fi
	exit 0
fi

# 收集URL列表
URLS=()
if [ $# -eq 0 ]; then
	echo "用法: $0 \"URL1\" \"URL2\" ... [model]"
	echo "      $0 urls.txt"
	echo "      $0 --status"
	echo "      $0 --log <task_id>"
	exit 1
fi

# 如果第一个参数是文件，从文件读取URL
if [ -f "$1" ]; then
	while IFS= read -r line || [ -n "$line" ]; do
		line=$(echo "$line" | xargs)
		[ -z "$line" ] && continue
		URLS+=("$line")
	done <"$1"
	shift
else
	# 收集所有URL参数（直到遇到模型名）
	MODEL="small"
	for arg in "$@"; do
		case "$arg" in
		tiny | base | small | medium | large-v3)
			MODEL="$arg"
			;;
		*)
			URLS+=("$arg")
			;;
		esac
	done
fi

if [ ${#URLS[@]} -eq 0 ]; then
	echo "错误：没有有效的URL"
	exit 1
fi

echo ">>> 添加 ${#URLS[@]} 个任务到队列"
echo "    模型: $MODEL"
echo ""

# 为每个URL创建任务
TASK_IDS=()
for url in "${URLS[@]}"; do
	# 生成任务ID
	BV=$(echo "$url" | grep -oP 'BV[\w]{10}' || echo "unknown")
	TS=$(date +%s)
	TASK_ID="${BV}_${TS}"
	TASK_IDS+=("$TASK_ID")

	LOG_FILE="$LOG_DIR/$TASK_ID.log"
	DONE_FILE="$LOG_DIR/$TASK_ID.done"
	FAIL_FILE="$LOG_DIR/$TASK_ID.fail"

	# 清除旧的标记文件
	rm -f "$DONE_FILE" "$FAIL_FILE"

	echo "[$TASK_ID] 加入队列: $url"

	# 启动后台任务
	(
		# 等待锁
		while ! mkdir "$LOCK_FILE" 2>/dev/null; do
			sleep 5
		done

		echo "=== 开始转录: $url ===" >>"$LOG_FILE"
		echo "时间: $(date '+%Y-%m-%d %H:%M:%S')" >>"$LOG_FILE"
		echo "模型: $MODEL" >>"$LOG_FILE"
		echo "" >>"$LOG_FILE"

		# 执行转录
		"$SCRIPT_DIR/script/bili_save.sh" "$url" "$MODEL" >>"$LOG_FILE" 2>&1
		EXIT_CODE=$?

		echo "" >>"$LOG_FILE"
		echo "退出码: $EXIT_CODE" >>"$LOG_FILE"
		echo "完成时间: $(date '+%Y-%m-%d %H:%M:%S')" >>"$LOG_FILE"

		# 释放锁
		rm -rf "$LOCK_FILE"

		# 标记结果
		if [ $EXIT_CODE -eq 0 ]; then
			touch "$DONE_FILE"
			echo "✓ [$TASK_ID] 完成"
		else
			touch "$FAIL_FILE"
			echo "✗ [$TASK_ID] 失败"
		fi
	) &
done

echo ""
echo ">>> 所有任务已提交后台运行"
echo "    查看状态: $0 --status"
echo "    查看日志: $0 --log <task_id>"
echo ""
echo "任务列表:"
for tid in "${TASK_IDS[@]}"; do
	echo "  - $tid"
done
