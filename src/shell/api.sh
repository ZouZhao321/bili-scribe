#!/bin/bash
# Bilibili Transcript API 服务管理脚本
#
# Usage: ./api.sh <command>
#   start   - 启动服务（后台守护进程）
#   stop    - 停止服务
#   restart - 重启服务
#   status  - 查看服务状态
#   logs    - 查看日志

SCRIPT_DIR="$(cd "$(dirname "$0")" && cd .. && pwd)"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python3"

if [ ! -f "$VENV_PYTHON" ]; then
	VENV_PYTHON="python3"
fi

APP="src.web.server:app"
PORT="${API_PORT:-8000}"
HOST="${API_HOST:-0.0.0.0}"
PID_FILE="/tmp/bilibili-api.pid"
LOG_FILE="/tmp/bilibili-api.log"

start_service() {
	if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
		echo "服务已在运行中 (PID: $(cat "$PID_FILE"))"
		exit 0
	fi

	echo "启动 Bilibili Transcript API..."
	echo "  地址: http://$HOST:$PORT"
	echo "  文档: http://$HOST:$PORT/docs"
	echo "  日志: $LOG_FILE"

	nohup "$VENV_PYTHON" -m uvicorn "$APP" \
		--host "$HOST" \
		--port "$PORT" \
		--log-level info \
		>>"$LOG_FILE" 2>&1 &

	PID=$!
	echo $PID >"$PID_FILE"

	# 等待启动完成
	sleep 2
	if kill -0 "$PID" 2>/dev/null; then
		echo "✓ 服务已启动 (PID: $PID)"
	else
		echo "✗ 服务启动失败，查看日志: $LOG_FILE"
		tail -5 "$LOG_FILE"
		exit 1
	fi
}

stop_service() {
	if [ ! -f "$PID_FILE" ]; then
		echo "服务未运行"
		return 0
	fi

	PID=$(cat "$PID_FILE")
	echo "停止服务 (PID: $PID)..."

	kill "$PID" 2>/dev/null
	sleep 2

	# 强制终止
	if kill -0 "$PID" 2>/dev/null; then
		kill -9 "$PID" 2>/dev/null
		sleep 1
	fi

	rm -f "$PID_FILE"
	echo "✓ 服务已停止"
}

status_service() {
	if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
		PID=$(cat "$PID_FILE")
		UPTIME=$(ps -o etime= -p "$PID" 2>/dev/null | xargs)
		echo "状态: 运行中"
		echo "  PID:    $PID"
		echo "  运行:   $UPTIME"
		echo "  端口:   $PORT"
		echo "  文档:   http://localhost:$PORT/docs"
		echo "  健康:   http://localhost:$PORT/api/v1/health"
		echo ""
		# 快速健康检查
		curl -s "http://localhost:$PORT/api/v1/health" 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "无法连接到服务"
	else
		echo "状态: 已停止"
	fi
}

logs_service() {
	if [ -f "$LOG_FILE" ]; then
		tail -f "$LOG_FILE"
	else
		echo "日志文件不存在: $LOG_FILE"
	fi
}

case "${1:-help}" in
start)
	start_service
	;;
stop)
	stop_service
	;;
restart)
	stop_service
	sleep 1
	start_service
	;;
status)
	status_service
	;;
logs)
	logs_service
	;;
help | *)
	echo "Bilibili Transcript API 管理"
	echo ""
	echo "用法: $0 <command>"
	echo ""
	echo "命令:"
	echo "  start   启动服务"
	echo "  stop    停止服务"
	echo "  restart 重启服务"
	echo "  status  查看服务状态"
	echo "  logs    查看日志"
	echo ""
	echo "环境变量:"
	echo "  API_PORT  端口 (默认: 8000)"
	echo "  API_HOST  地址 (默认: 0.0.0.0)"
	echo ""
	echo "示例:"
	echo "  $0 start"
	echo "  API_PORT=8080 $0 start"
	echo "  $0 status"
	echo "  $0 stop"
	;;
esac
