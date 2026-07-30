#!/usr/bin/env bash
# Whisper 内存压力测试 — 可复用验证脚本
#
# 用法:
#   bash verify.sh                   # 完整测试（small + medium + large-v3，耗时较长）
#   bash verify.sh quick             # 快速测试（仅 small 模型）
#   bash verify.sh check             # 仅检查系统环境，不运行转录
#
# 测试内容:
#   1. 系统环境检查（内存、Swap、磁盘）
#   2. 模型加载内存消耗记录
#   3. 转录完成后资源释放验证
#   4. 三个模型质量对比
#
# 前置条件:
#   - 在项目根目录运行（bilibili-transcript/）
#   - Python 虚拟环境已激活（faster-whisper 已安装）
#   - 测试视频 URL 或 BV 号

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python3"

# 如果没有 venv，回退到系统 Python
if [ ! -f "$VENV_PYTHON" ]; then
	VENV_PYTHON="python3"
fi

TRANSCRIPT_SCRIPT="$PROJECT_DIR/src/fetch_transcript.py"

# 参数解析：如果第一个参数是模式关键字，则使用默认 URL
# 否则第一个参数是 URL，第二个参数是模式
case "${1:-}" in
check | quick | all)
	MODE="$1"
	TEST_URL="${2:-BV1DqKr6SEyo}"
	;;
*)
	TEST_URL="${1:-BV1DqKr6SEyo}"
	MODE="${2:-all}"
	;;
esac

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log() { echo -e "${CYAN}[$(date '+%H:%M:%S')]${NC} $1"; }
ok() { echo -e "  ${GREEN}✅${NC} $1"; }
warn() { echo -e "  ${YELLOW}⚠️${NC} $1"; }
fail() { echo -e "  ${RED}❌${NC} $1"; }

# ============================================================
# 1. 系统环境检查
# ============================================================
check_system() {
	echo ""
	echo "=========================================="
	echo "  系统环境检查"
	echo "=========================================="

	# CPU
	local cpu_cores
	cpu_cores=$(nproc 2>/dev/null || echo "unknown")
	local cpu_model
	cpu_model=$(grep "model name" /proc/cpuinfo | head -1 | cut -d: -f2 | sed 's/^ //' 2>/dev/null || echo "unknown")
	log "CPU: $cpu_cores 核 — $cpu_model"

	# 内存
	local mem_total
	mem_total=$(free -h | awk '/^Mem:/{print $2}')
	local mem_avail
	mem_avail=$(free -h | awk '/^Mem:/{print $7}')
	log "内存: 总计 $mem_total, 可用 $mem_avail"

	# Swap
	local swap_total
	swap_total=$(free -h | awk '/^Swap:/{print $2}')
	local swap_used
	swap_used=$(free -h | awk '/^Swap:/{print $3}')
	log "Swap: 总计 $swap_total, 已用 $swap_used"

	# 磁盘
	local disk_avail
	disk_avail=$(df -h / | awk 'NR==2{print $4}')
	log "磁盘可用: $disk_avail"

	# 检查 faster-whisper
	if $VENV_PYTHON -c "import faster_whisper; print(faster_whisper.__version__)" 2>/dev/null; then
		local wh_version
		wh_version=$($VENV_PYTHON -c "import faster_whisper; print(faster_whisper.__version__)" 2>/dev/null)
		ok "faster-whisper $wh_version 已安装"
	else
		fail "faster-whisper 未安装！请先运行: uv pip install faster-whisper"
		return 1
	fi

	# 检查已缓存的模型
	echo ""
	log "已缓存的 Whisper 模型:"
	local cache_dir="$HOME/.cache/huggingface/hub"
	if [ -d "$cache_dir" ]; then
		for model in tiny base small medium large-v3 large-v2; do
			local model_path="$cache_dir/models--Systran--faster-whisper-$model"
			if [ -d "$model_path" ]; then
				local size
				size=$(du -sh "$model_path" 2>/dev/null | cut -f1)
				ok "$model ($size)"
			fi
		done
	else
		warn "未找到 HuggingFace 缓存目录"
	fi

	# 内存评估
	echo ""
	log "内存评估:"
	local mem_mb
	mem_mb=$(free -m | awk '/^Mem:/{print $2}')
	if [ "$mem_mb" -ge 4096 ]; then
		ok "4GB+ RAM — 适合运行 large-v3 模型"
	elif [ "$mem_mb" -ge 2048 ]; then
		warn "2-4GB RAM — 建议使用 small 或 medium 模型"
	else
		fail "2GB 以下 RAM — 建议仅使用 tiny/small 模型"
	fi

	local swap_mb
	swap_mb=$(free -m | awk '/^Swap:/{print $2}')
	if [ "$swap_mb" -ge 4096 ]; then
		ok "Swap >= 4GB — 足够运行 large-v3"
	elif [ "$swap_mb" -ge 2048 ]; then
		warn "Swap 2-4GB — medium 模型可用，large-v3 有风险"
	elif [ "$swap_mb" -eq 0 ]; then
		fail "没有 Swap！建议至少配置 4GB Swap"
	else
		warn "Swap < 2GB — 仅能运行 small 模型"
	fi

	echo ""
	read -r -p "按回车继续测试，或 Ctrl+C 退出..."
}

# ============================================================
# 2. 运行转录测试
# ============================================================
run_test() {
	local model=$1
	local label=$2

	echo ""
	echo "=========================================="
	echo "  测试: $label ($model)"
	echo "=========================================="

	# 记录开始前内存
	local mem_before
	mem_before=$(free -m | awk '/^Mem:/{printf "%s (可用 %s)", $2, $7}')
	local swap_before
	swap_before=$(free -m | awk '/^Swap:/{printf "%s (已用 %s)", $2, $3}')

	log "开始前 — 内存: $mem_before, Swap: $swap_before"

	# 记录开始时间
	local start_time
	start_time=$(date +%s)

	# 运行转录
	log "正在转录（$model），请稍候..."
	local output
	output=$($VENV_PYTHON "$TRANSCRIPT_SCRIPT" "$TEST_URL" --text-only --model "$model" 2>&1) || {
		local exit_code=$?
		fail "转录失败 (exit code: $exit_code)"
		echo "$output" | tail -10
		return 1
	}

	local end_time
	end_time=$(date +%s)
	local elapsed=$((end_time - start_time))

	# 记录结束后内存
	local mem_after
	mem_after=$(free -m | awk '/^Mem:/{printf "%s (可用 %s)", $2, $7}')
	local swap_after
	swap_after=$(free -m | awk '/^Swap:/{printf "%s (已用 %s)", $2, $3}')

	# 解析结果
	local segments
	segments=$(echo "$output" | grep "Whisper:" | grep -oP '\d+(?= segments)' || echo "?")
	local title
	title=$(echo "$output" | grep "^# " | head -1 || echo "无标题")

	log "完成！耗时 ${elapsed}秒"
	ok "分段数: $segments"
	ok "结束后 — 内存: $mem_after, Swap: $swap_after"
	ok "标题: $title"

	# 保存结果到临时文件
	local result_file="$SCRIPT_DIR/result_${model}.txt"
	echo "$output" >"$result_file"
	ok "文稿已保存: $result_file"

	# 提取关键短语做质量检查
	echo ""
	log "关键词汇识别检查:"
	for keyword in "冰美式" "DIY" "K3集群" "挂件" "拖拉拽" "示例" "伪需求"; do
		if echo "$output" | grep -q "$keyword"; then
			ok "识别到: $keyword"
		else
			warn "未识别: $keyword"
		fi
	done
}

# ============================================================
# 3. 汇总报告
# ============================================================
print_summary() {
	echo ""
	echo "=========================================="
	echo "  测试汇总"
	echo "=========================================="
	echo ""
	free -h
	echo ""

	log "输出文件:"
	ls -lh "$SCRIPT_DIR"/result_*.txt 2>/dev/null | while read -r line; do
		echo "  $line"
	done

	echo ""
	echo "测试结果已保存到: $SCRIPT_DIR/"
	echo "完整记录: $SCRIPT_DIR/README.md"
	echo "详细数据: $SCRIPT_DIR/results.md"
}

# ============================================================
# Main
# ============================================================
main() {
	echo ""
	echo "╔══════════════════════════════════════════════╗"
	echo "║   Whisper 内存压力测试验证脚本               ║"
	echo "║   项目: bilibili-transcript                  ║"
	echo "╚══════════════════════════════════════════════╝"
	echo "测试视频: $TEST_URL"
	echo "模式: $MODE"
	echo ""

	if [ "$MODE" = "check" ]; then
		check_system
		exit 0
	fi

	check_system

	# 运行测试
	run_test "small" "small (464MB)"
	echo ""

	if [ "$MODE" != "quick" ]; then
		run_test "medium" "medium (1.5GB)"
		echo ""
		run_test "large-v3" "large-v3 (2.9GB)"
	fi

	print_summary

	echo ""
	echo "=========================================="
	echo "  ${GREEN}测试完成${NC}"
	echo "=========================================="
	echo ""
	echo "如需重新测试，运行:"
	echo "  bash $0 $TEST_URL"
	echo "  bash $0 $TEST_URL quick    # 仅 small"
	echo "  bash $0 $TEST_URL check    # 仅检查环境"
}

main
