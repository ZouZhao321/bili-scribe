#!/bin/bash
# bili_queue.sh - 持久化任务队列 + cron 定时调度
# 用于 B 站视频批量转录，失败自动重试（最多 3 次）
#
# 原理:
#   cron 每10分钟调用一次 "bili_queue.sh cron"
#   检查是否有待处理任务，且当前无任务在运行 → 取一个执行
#   失败自动重试，最多 3 次
#
# 用法:
#   ./bili_queue.sh add <URL> [model]           # 添加任务到队列
#   ./bili_queue.sh cron                         # 定时处理（由 cron 调用）
#   ./bili_queue.sh status                       # 查看队列状态
#   ./bili_queue.sh list [pending|running|done|failed]  # 列出任务
#   ./bili_queue.sh retry <id>                   # 重试失败任务
#   ./bili_queue.sh remove <id>                  # 删除任务
#   ./bili_queue.sh cancel                       # 取消当前运行的任务
#   ./bili_queue.sh clear [pending|failed]       # 清空队列
#   ./bili_queue.sh install-cron                 # 安装 crontab
#   ./bili_queue.sh uninstall-cron               # 卸载 crontab
#
# 示例:
#   ./bili_queue.sh add "https://www.bilibili.com/video/BV1xx"
#   ./bili_queue.sh add "https://b23.tv/xxx" small
#   ./bili_queue.sh add "https://www.bilibili.com/video/BV1xx" medium
#   ./bili_queue.sh install-cron                 # 之后 cron 会自动处理

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
QUEUE_DIR="$HOME/.queue"
LOCK_DIR="$QUEUE_DIR/lock"
PENDING_DIR="$QUEUE_DIR/pending"
RUNNING_DIR="$QUEUE_DIR/running"
DONE_DIR="$QUEUE_DIR/done"
FAILED_DIR="$QUEUE_DIR/failed"
LOG_FILE="$QUEUE_DIR/cron.log"

MAX_RETRIES=3
# 任务运行超时（秒），超过此时间视为僵死任务
# 默认 6 小时，大模型可能需要更长时间
TIMEOUT=$((6 * 3600))

# CPU 空闲阈值：CPU 使用率低于此值才启动新任务（0-100）
# 系统 CPU 忙时跳过，闲时自动处理
CPU_THRESHOLD=50

# 使用项目的 venv Python
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python3"
TRANSCRIPT_SCRIPT="$SCRIPT_DIR/src/fetch_transcript.py"
SAVE_SCRIPT="$SCRIPT_DIR/bili_save.sh"

# 如果 venv 不存在，回退到系统 Python
if [ ! -f "$VENV_PYTHON" ]; then
    VENV_PYTHON="python3"
fi

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 确保目录存在
init_dirs() {
    mkdir -p "$PENDING_DIR" "$RUNNING_DIR" "$DONE_DIR" "$FAILED_DIR"
}

# 生成任务 ID: YYYYMMDD_HHMMSS_BVID
generate_task_id() {
    local url="$1"
    local bv=""
    bv=$(echo "$url" | grep -oP 'BV[\w]{10}' || echo "unknown")
    echo "$(date +%Y%m%d_%H%M%S)_${bv}"
}

# 提取 BV ID
extract_bv() {
    local url="$1"
    local bv
    bv=$(echo "$url" | grep -oP 'BV[\w]{10}')
    if [ -n "$bv" ]; then
        echo "$bv"
        return 0
    fi
    # 尝试通过 API 解析（b23.tv 短链接等）
    bv=$("$VENV_PYTHON" -c "
import sys, re, urllib.request, json
url = '$url'
headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.bilibili.com'}
if 'b23.tv' in url:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            url = resp.url
    except: pass
m = re.search(r'(BV[\w]{10})', url)
if m:
    print(m.group(1))
    sys.exit(0)
m = re.search(r'av(\d+)', url)
if m:
    aid = m.group(1)
    data = json.loads(urllib.request.urlopen(urllib.request.Request(f'https://api.bilibili.com/x/web-interface/view?aid={aid}', headers=headers), timeout=15).read())
    if data.get('code') == 0:
        print(data['data']['bvid'])
        sys.exit(0)
print('ERROR')
sys.exit(1)
" 2>/dev/null)
    if [ "$bv" != "ERROR" ] && [ -n "$bv" ]; then
        echo "$bv"
        return 0
    fi
    echo "unknown"
    return 1
}

# 获取锁（原子操作）
acquire_lock() {
    if mkdir "$LOCK_DIR" 2>/dev/null; then
        return 0
    fi
    return 1
}

# 释放锁
release_lock() {
    rm -rf "$LOCK_DIR" 2>/dev/null
}

# 创建任务文件
create_task_file() {
    local task_id="$1"
    local url="$2"
    local model="$3"
    local task_file="$PENDING_DIR/${task_id}.task"
    cat > "$task_file" << EOF
url=${url}
model=${model}
retries=0
created_at=$(date '+%Y-%m-%d %H:%M:%S')
EOF
    echo "$task_file"
}

# 读取任务文件的字段值
read_task_field() {
    local task_file="$1"
    local field="$2"
    grep "^${field}=" "$task_file" 2>/dev/null | cut -d'=' -f2-
}

# 更新任务文件的字段值
update_task_field() {
    local task_file="$1"
    local field="$2"
    local value="$3"
    if [ -f "$task_file" ]; then
        if grep -q "^${field}=" "$task_file"; then
            sed -i "s|^${field}=.*|${field}=${value}|" "$task_file"
        else
            echo "${field}=${value}" >> "$task_file"
        fi
    fi
}

# 获取当前 CPU 使用率（百分比 0-100）
# 通过读取 /proc/stat 两次（间隔 1 秒）计算
# 不需要外部依赖，纯 bash 实现
get_cpu_usage() {
    local cpu user nice system idle iowait irq softirq steal guest guest_nice
    local idle1 total1 idle2 total2

    # 第一次读取（捕获所有字段，Linux 2.6+ 有 guest/guest_nice）
    read -r cpu user nice system idle iowait irq softirq steal guest guest_nice < /proc/stat 2>/dev/null || return 0
    idle1=$((idle + iowait))
    total1=$((user + nice + system + idle + iowait + irq + softirq + steal + guest + guest_nice))

    sleep 1

    # 第二次读取
    read -r cpu user nice system idle iowait irq softirq steal guest guest_nice < /proc/stat 2>/dev/null || return 0
    idle2=$((idle + iowait))
    total2=$((user + nice + system + idle + iowait + irq + softirq + steal + guest + guest_nice))

    # 计算 CPU 使用率
    local total_delta=$((total2 - total1))
    local idle_delta=$((idle2 - idle1))

    if [ "$total_delta" -le 0 ]; then
        echo 0
        return
    fi

    local usage=$((100 * (total_delta - idle_delta) / total_delta))
    echo "$usage"
}

# 检查任务是否超时（僵死任务检测）
is_task_stale() {
    local task_file="$1"
    if [ ! -f "$task_file" ]; then
        return 1
    fi
    local started_at
    started_at=$(read_task_field "$task_file" "started_at")
    if [ -z "$started_at" ]; then
        return 1
    fi
    # 计算已运行秒数
    local start_epoch end_epoch elapsed
    start_epoch=$(date -d "$started_at" +%s 2>/dev/null)
    if [ -z "$start_epoch" ]; then
        return 1
    fi
    end_epoch=$(date +%s)
    elapsed=$((end_epoch - start_epoch))
    if [ "$elapsed" -gt "$TIMEOUT" ]; then
        return 0  # 超时了
    fi
    return 1  # 未超时
}

# ========================
# 命令实现
# ========================

# 添加任务到队列
cmd_add() {
    local url="$1"
    local model="${2:-small}"

    if [ -z "$url" ]; then
        echo "用法: $0 add <URL> [model]"
        echo "  model: tiny / base / small (默认) / medium / large-v3"
        exit 1
    fi

    # 验证模型名
    case "$model" in
        tiny|base|small|medium|large-v3) ;;
        *) echo "错误: 无效模型 '$model'，可选: tiny/base/small/medium/large-v3"; exit 1;;
    esac

    # 检查 URL 是否有效
    local bv
    bv=$(extract_bv "$url")
    if [ "$bv" = "unknown" ]; then
        echo -e "${YELLOW}⚠ 警告: 无法解析 BV ID，但任务仍会加入队列${NC}"
    fi

    init_dirs

    local task_id
    task_id=$(generate_task_id "$url")
    local task_file
    task_file=$(create_task_file "$task_id" "$url" "$model")

    echo -e "${GREEN}✓${NC} 任务已加入队列: ${BLUE}${task_id}${NC}"
    echo "  URL:   $url"
    echo "  Model: $model"
    if [ -n "$bv" ] && [ "$bv" != "unknown" ]; then
        echo "  BV:    $bv"
    fi
}

# 定时处理（由 cron 每10分钟调用）
cmd_cron() {
    init_dirs

    # 获取锁，避免并发
    if ! acquire_lock; then
        # 无法获取锁，另一个 cron 进程正在操作
        exit 0
    fi

    # 检查是否有任务在运行
    local running_task
    running_task=$(ls "$RUNNING_DIR"/*.task 2>/dev/null | head -1)

    if [ -n "$running_task" ]; then
        # 检查是否超时（僵死任务）
        if is_task_stale "$running_task"; then
            local task_id
            task_id=$(basename "$running_task" .task)
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⚠ 任务 $task_id 运行超时，重新放回队列" >> "$LOG_FILE"
            # 重试计数 +1
            local retries
            retries=$(read_task_field "$running_task" "retries")
            retries=$((retries + 1))
            update_task_field "$running_task" "retries" "$retries"

            if [ "$retries" -ge "$MAX_RETRIES" ]; then
                mv "$running_task" "$FAILED_DIR/"
                echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✗ 任务 $task_id 超时，已超过最大重试次数" >> "$LOG_FILE"
            else
                mv "$running_task" "$PENDING_DIR/"
                echo "[$(date '+%Y-%m-%d %H:%M:%S')] ↻ 任务 $task_id 超时，放回队列（重试 $retries/$MAX_RETRIES）" >> "$LOG_FILE"
            fi
        else
            # 有任务正常运行中，跳过
            release_lock
            exit 0
        fi
    fi

    # 取下一个待处理任务
    local pending_task
    pending_task=$(ls "$PENDING_DIR"/*.task 2>/dev/null | sort | head -1)

    if [ -z "$pending_task" ]; then
        # 没有待处理任务
        release_lock
        exit 0
    fi

    # CPU 使用率检查：系统忙时跳过，闲时再处理
    local cpu_usage
    cpu_usage=$(get_cpu_usage)
    if [ "$cpu_usage" -gt "$CPU_THRESHOLD" ]; then
        local task_id_skip
        task_id_skip=$(basename "$pending_task" .task)
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⏸ CPU ${cpu_usage}% > ${CPU_THRESHOLD}%，跳过任务 $task_id_skip" >> "$LOG_FILE"
        release_lock
        exit 0
    fi

    # 读取任务信息
    local url model retries
    url=$(read_task_field "$pending_task" "url")
    model=$(read_task_field "$pending_task" "model")
    retries=$(read_task_field "$pending_task" "retries")
    [ -z "$model" ] && model="small"
    [ -z "$retries" ] && retries=0

    local task_id
    task_id=$(basename "$pending_task" .task)

    # 标记开始时间 → 移入运行目录
    update_task_field "$pending_task" "started_at" "$(date '+%Y-%m-%d %H:%M:%S')"
    mv "$pending_task" "$RUNNING_DIR/"
    local running_task="$RUNNING_DIR/${task_id}.task"

    # 释放锁，开始执行任务
    release_lock

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ▶ 开始处理: $task_id" >> "$LOG_FILE"
    echo "  URL: $url" >> "$LOG_FILE"
    echo "  Model: $model" >> "$LOG_FILE"

    # 执行转录（调用 bili_save.sh 复用完整流程）
    # 输出重定向到临时日志
    local task_log
    task_log=$(mktemp /tmp/bili_task_${task_id}.XXXXXX.log)
    bash "$SAVE_SCRIPT" "$url" "$model" > "$task_log" 2>&1
    local exit_code=$?

    # 获取锁，更新状态
    local max_wait=30
    local waited=0
    while ! acquire_lock; do
        sleep 1
        waited=$((waited + 1))
        if [ "$waited" -ge "$max_wait" ]; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⚠ 无法获取锁更新状态，任务状态可能不一致" >> "$LOG_FILE"
            break
        fi
    done

    if [ "$exit_code" -eq 0 ]; then
        # 成功
        mv "$running_task" "$DONE_DIR/"
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✓ 完成: $task_id" >> "$LOG_FILE"
        cat "$task_log" >> "$LOG_FILE"
    else
        # 失败
        retries=$((retries + 1))
        update_task_field "$running_task" "retries" "$retries"
        update_task_field "$running_task" "last_error" "$(tail -3 "$task_log" | tr '\n' ' ' | head -c 200)"

        if [ "$retries" -ge "$MAX_RETRIES" ]; then
            mv "$running_task" "$FAILED_DIR/"
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✗ 失败（已达最大重试次数）: $task_id" >> "$LOG_FILE"
        else
            mv "$running_task" "$PENDING_DIR/"
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] ↻ 失败，放回队列（重试 $retries/$MAX_RETRIES）: $task_id" >> "$LOG_FILE"
        fi
        cat "$task_log" >> "$LOG_FILE"
    fi

    rm -f "$task_log"

    # 如果获取到了锁，释放
    if [ -d "$LOCK_DIR" ]; then
        release_lock
    fi
}

# 查看队列状态
cmd_status() {
    init_dirs

    local pending_count=0
    local running_count=0
    local done_count=0
    local failed_count=0

    pending_count=$(ls "$PENDING_DIR"/*.task 2>/dev/null | wc -l)
    running_count=$(ls "$RUNNING_DIR"/*.task 2>/dev/null | wc -l)
    done_count=$(ls "$DONE_DIR"/*.task 2>/dev/null | wc -l)
    failed_count=$(ls "$FAILED_DIR"/*.task 2>/dev/null | wc -l)

    echo "========================================"
    echo "  Bilibili 转录队列状态"
    echo "========================================"
    echo ""

    # 正在运行
    local running_task
    running_task=$(ls "$RUNNING_DIR"/*.task 2>/dev/null | head -1)
    if [ -n "$running_task" ]; then
        local task_id url model started_at elapsed
        task_id=$(basename "$running_task" .task)
        url=$(read_task_field "$running_task" "url")
        model=$(read_task_field "$running_task" "model")
        started_at=$(read_task_field "$running_task" "started_at")
        echo -e "  ▶ ${GREEN}正在运行${NC}"
        echo "    ID:     $task_id"
        echo "    URL:    $url"
        echo "    Model:  $model"
        echo "    Started: $started_at"
        if [ -n "$started_at" ]; then
            local start_epoch end_epoch
            start_epoch=$(date -d "$started_at" +%s 2>/dev/null)
            end_epoch=$(date +%s)
            elapsed=$((end_epoch - start_epoch))
            if [ "$elapsed" -gt 60 ]; then
                echo "    Elapsed: $((elapsed / 60)) 分钟"
            else
                echo "    Elapsed: ${elapsed} 秒"
            fi
        fi
        echo ""
    else
        echo -e "  ▶ ${YELLOW}当前无运行中的任务${NC}"
        echo ""
    fi

    # 当前 CPU 使用率
    local cpu_usage
    cpu_usage=$(get_cpu_usage)

    echo "  📊 统计"
    echo -e "    ${BLUE}待处理:${NC} $pending_count"
    echo -e "    ${GREEN}已完成:${NC} $done_count"
    echo -e "    ${RED}失败:${NC}   $failed_count"
    echo ""

    echo "  ⚡ 系统状态"
    if [ "$cpu_usage" -le "$CPU_THRESHOLD" ]; then
        echo -e "    CPU: ${GREEN}${cpu_usage}%${NC} (空闲，可处理任务)"
    else
        echo -e "    CPU: ${RED}${cpu_usage}%${NC} (繁忙，阈值 ${CPU_THRESHOLD}%)"
    fi
    echo ""

    # 最近的 cron 日志
    if [ -f "$LOG_FILE" ]; then
        echo "  📝 最近日志:"
        tail -5 "$LOG_FILE" | sed 's/^/    /'
        echo ""
    fi

    # 提示
    if [ "$pending_count" -gt 0 ]; then
        if [ -z "$running_task" ]; then
            if [ "$cpu_usage" -le "$CPU_THRESHOLD" ]; then
                echo -e "  ${GREEN}💡 CPU 空闲，队列有 $pending_count 个任务待处理${NC}"
                echo "     cron 将在 1 分钟内自动开始处理"
            else
                echo -e "  ${YELLOW}💡 队列有 $pending_count 个任务，CPU ${cpu_usage}% 繁忙，等待中...${NC}"
            fi
        fi
    fi
}

# 列出任务
cmd_list() {
    local filter="$1"
    init_dirs

    list_tasks() {
        local dir="$1"
        local label="$2"
        local color="$3"
        local files
        files=$(ls "$dir"/*.task 2>/dev/null | sort)
        if [ -z "$files" ]; then
            return
        fi
        echo -e "${color}${label}${NC}:"
        for f in $files; do
            local task_id url model retries
            task_id=$(basename "$f" .task)
            url=$(read_task_field "$f" "url")
            model=$(read_task_field "$f" "model")
            retries=$(read_task_field "$f" "retries")
            local extra=""
            if [ "$label" = "失败" ]; then
                local last_error
                last_error=$(read_task_field "$f" "last_error" | head -c 80)
                extra=" 错误: ${last_error}"
            fi
            if [ "$label" = "已完成" ]; then
                echo "  ✓ $task_id"
                echo "    URL: $url | Model: $model"
            elif [ "$label" = "失败" ]; then
                echo "  ✗ $task_id (重试 ${retries}/${MAX_RETRIES})"
                echo "    URL: $url | Model: $model${extra}"
            elif [ "$label" = "待处理" ]; then
                echo "  ○ $task_id"
                echo "    URL: $url | Model: $model | 重试: ${retries}/${MAX_RETRIES}"
            elif [ "$label" = "运行中" ]; then
                local started_at
                started_at=$(read_task_field "$f" "started_at")
                echo "  ▶ $task_id"
                echo "    URL: $url | Model: $model | 开始: $started_at"
            fi
        done
        echo ""
    }

    case "$filter" in
        pending)
            list_tasks "$PENDING_DIR" "待处理" "$BLUE"
            ;;
        running)
            list_tasks "$RUNNING_DIR" "运行中" "$GREEN"
            ;;
        done)
            list_tasks "$DONE_DIR" "已完成" "$GREEN"
            ;;
        failed)
            list_tasks "$FAILED_DIR" "失败" "$RED"
            ;;
        "")
            list_tasks "$PENDING_DIR" "待处理" "$BLUE"
            list_tasks "$RUNNING_DIR" "运行中" "$GREEN"
            list_tasks "$DONE_DIR" "已完成" "$GREEN"
            list_tasks "$FAILED_DIR" "失败" "$RED"
            ;;
        *)
            echo "用法: $0 list [pending|running|done|failed]"
            exit 1
            ;;
    esac
}

# 重试失败任务
cmd_retry() {
    local task_id="$1"
    if [ -z "$task_id" ]; then
        echo "用法: $0 retry <task_id>"
        echo "提示: 使用 '$0 list failed' 查看失败任务"
        exit 1
    fi

    local task_file="$FAILED_DIR/${task_id}.task"
    if [ ! -f "$task_file" ]; then
        echo "错误: 未找到任务 $task_id"
        echo "使用 '$0 list failed' 查看失败任务"
        exit 1
    fi

    # 重置重试计数
    update_task_field "$task_file" "retries" "0"
    update_task_field "$task_file" "last_error" ""
    mv "$task_file" "$PENDING_DIR/"
    echo -e "${GREEN}✓${NC} 任务 $task_id 已放回队列，准备重试"
}

# 删除任务
cmd_remove() {
    local task_id="$1"
    if [ -z "$task_id" ]; then
        echo "用法: $0 remove <task_id>"
        exit 1
    fi

    local found=0
    for dir in "$PENDING_DIR" "$RUNNING_DIR" "$DONE_DIR" "$FAILED_DIR"; do
        local f="$dir/${task_id}.task"
        if [ -f "$f" ]; then
            rm -f "$f"
            echo -e "${GREEN}✓${NC} 已删除任务 $task_id"
            found=1
            break
        fi
    done

    if [ "$found" -eq 0 ]; then
        echo "错误: 未找到任务 $task_id"
        exit 1
    fi
}

# 取消当前运行的任务
cmd_cancel() {
    local running_task
    running_task=$(ls "$RUNNING_DIR"/*.task 2>/dev/null | head -1)
    if [ -z "$running_task" ]; then
        echo "当前没有运行中的任务"
        exit 0
    fi

    local task_id
    task_id=$(basename "$running_task" .task)
    local url
    url=$(read_task_field "$running_task" "url")

    echo -e "${YELLOW}⚠ 正在取消任务: $task_id${NC}"
    echo "  URL: $url"

    # 杀掉关联的 bili_save.sh 和 python 进程
    # 通过匹配 task_id 来查找，但 task_id 不在进程名中，所以用 PID 文件
    # 或者更简单：杀掉所有 bili_save.sh 和 fetch_transcript.py 进程
    pkill -f "bili_save.sh.*$url" 2>/dev/null
    pkill -f "fetch_transcript.py.*$url" 2>/dev/null

    # 移回待处理队列，重置重试计数
    update_task_field "$running_task" "retries" "0"
    update_task_field "$running_task" "last_error" "cancelled"
    mv "$running_task" "$PENDING_DIR/"

    echo -e "${GREEN}✓${NC} 任务已取消并放回队列"
}

# 清空队列
cmd_clear() {
    local target="$1"

    case "$target" in
        pending)
            rm -f "$PENDING_DIR"/*.task
            echo -e "${GREEN}✓${NC} 已清空待处理队列"
            ;;
        failed)
            rm -f "$FAILED_DIR"/*.task
            echo -e "${GREEN}✓${NC} 已清空失败任务"
            ;;
        "")
            local pending_count failed_count
            pending_count=$(ls "$PENDING_DIR"/*.task 2>/dev/null | wc -l)
            failed_count=$(ls "$FAILED_DIR"/*.task 2>/dev/null | wc -l)
            local total=$((pending_count + failed_count))
            if [ "$total" -eq 0 ]; then
                echo "队列已空"
                exit 0
            fi
            echo -e "${YELLOW}⚠ 将删除 $total 个任务（${pending_count} 待处理 + ${failed_count} 失败）${NC}"
            echo -n "确认？(y/N): "
            read -r confirm
            if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
                rm -f "$PENDING_DIR"/*.task "$FAILED_DIR"/*.task
                echo -e "${GREEN}✓${NC} 已清空队列"
            else
                echo "已取消"
            fi
            ;;
        *)
            echo "用法: $0 clear [pending|failed]"
            exit 1
            ;;
    esac
}

# 安装 crontab
cmd_install_cron() {
    local script_path
    script_path=$(readlink -f "$0" 2>/dev/null || echo "$SCRIPT_DIR/$(basename "$0")")

    # 创建 crontab 条目（每10分钟运行）
    local cron_entry="*/10 * * * * ${script_path} cron >> ${QUEUE_DIR}/cron.log 2>&1"

    # 检查是否已安装
    if crontab -l 2>/dev/null | grep -q "$script_path"; then
        echo -e "${YELLOW}⚠ crontab 已存在，将更新${NC}"
    fi

    # 添加或更新 crontab
    (crontab -l 2>/dev/null | grep -v "$script_path"; echo "$cron_entry") | crontab -

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓${NC} crontab 已安装"
        echo "  条目: $cron_entry"
        echo "  日志: $QUEUE_DIR/cron.log"
        echo ""
        echo -e "${YELLOW}💡 提示:${NC} cron 将每10分钟检查一次队列"
        echo "  CPU 空闲时 → 自动开始处理"
        echo "  CPU 繁忙时 → 跳过，等待下次检查"
        echo "  可以在任意时间通过 '$0 add <URL>' 添加任务"
    else
        echo -e "${RED}✗${NC} 安装 crontab 失败"
        exit 1
    fi
}

# 卸载 crontab
cmd_uninstall_cron() {
    local script_path
    script_path=$(readlink -f "$0" 2>/dev/null || echo "$SCRIPT_DIR/$(basename "$0")")

    if crontab -l 2>/dev/null | grep -q "$script_path"; then
        (crontab -l 2>/dev/null | grep -v "$script_path") | crontab -
        echo -e "${GREEN}✓${NC} crontab 已卸载"
    else
        echo -e "${YELLOW}⚠ 未找到相关的 crontab 条目${NC}"
    fi
}

# ========================
# 主入口
# ========================

main() {
    local cmd="$1"
    shift 2>/dev/null

    case "$cmd" in
        add)
            cmd_add "$@"
            ;;
        cron)
            cmd_cron
            ;;
        status)
            cmd_status
            ;;
        list)
            cmd_list "$1"
            ;;
        retry)
            cmd_retry "$1"
            ;;
        remove)
            cmd_remove "$1"
            ;;
        cancel)
            cmd_cancel
            ;;
        clear)
            cmd_clear "$1"
            ;;
        install-cron)
            cmd_install_cron
            ;;
        uninstall-cron)
            cmd_uninstall_cron
            ;;
        "")
            echo "Bilibili 转录队列管理"
            echo "用法: $0 <command> [args]"
            echo ""
            echo "命令:"
            echo "  add <URL> [model]         添加任务到队列"
            echo "  cron                      定时处理（由 cron 调用）"
            echo "  status                    查看队列状态"
            echo "  list [status]             列出任务"
            echo "  retry <id>                重试失败任务"
            echo "  remove <id>               删除任务"
            echo "  cancel                    取消当前运行的任务"
            echo "  clear [pending|failed]    清空队列"
            echo "  install-cron              安装 crontab"
            echo "  uninstall-cron            卸载 crontab"
            echo ""
            echo "调度策略:"
            echo "  CPU 占用率 < ${CPU_THRESHOLD}% → 自动取任务执行"
            echo "  CPU 占用率 ≥ ${CPU_THRESHOLD}% → 跳过，下次再检查"
            echo "  失败自动重试，最多 ${MAX_RETRIES} 次"
            echo ""
            echo "示例:"
            echo "  $0 add \"https://www.bilibili.com/video/BV1xx\""
            echo "  $0 add \"https://b23.tv/xxx\" small"
            echo "  $0 status"
            echo "  $0 install-cron"
            ;;
        *)
            echo "错误: 未知命令 '$cmd'"
            echo "用法: $0 <add|cron|status|list|retry|remove|cancel|clear|install-cron|uninstall-cron>"
            exit 1
            ;;
    esac
}

main "$@"