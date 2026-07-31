#!/usr/bin/env python3
"""Bilibili 转录任务队列 — 持久化队列 + cron 定时调度.

用法:
    bili_queue.py add <URL> [model]              添加任务到队列
    bili_queue.py cron                            定时处理（由 cron 调用）
    bili_queue.py status                          查看队列状态
    bili_queue.py list [pending|running|done|failed]  列出任务
    bili_queue.py retry <id>                      重试失败任务
    bili_queue.py remove <id>                     删除任务
    bili_queue.py cancel                          取消当前运行的任务
    bili_queue.py clear [pending|failed]          清空队列
    bili_queue.py install-cron                    安装 crontab
    bili_queue.py uninstall-cron                  卸载 crontab

调度策略:
    - CPU 占用率 < 50% → 自动取任务执行
    - CPU 占用率 ≥ 50% → 跳过，下次再检查
    - 失败自动重试，最多 3 次
    - 任务运行超 6 小时视为僵死，放回队列重试
"""

import argparse
import json
import logging
import subprocess
import sys
import time
import urllib.error
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# 项目路径
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.bilibili import (  # noqa: E402
    download_audio,
    download_subtitle_json,
    extract_bvid,
    get_audio_url,
    get_cid,
    get_subtitle_url,
    get_video_info,
)
from src.core.transcriber import whisper_transcribe  # noqa: E402

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
QUEUE_DIR = Path.home() / ".queue"
PENDING_DIR = QUEUE_DIR / "pending"
RUNNING_DIR = QUEUE_DIR / "running"
DONE_DIR = QUEUE_DIR / "done"
FAILED_DIR = QUEUE_DIR / "failed"
LOCK_FILE = QUEUE_DIR / "queue.lock"
TASKS_FILE = QUEUE_DIR / "tasks.json"
LOG_FILE = QUEUE_DIR / "cron.log"

MAX_RETRIES = 3
TIMEOUT = 6 * 3600  # 6 小时
CPU_THRESHOLD = 50
OUTPUT_DIR = PROJECT_ROOT / "out"

# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------
_log_configured = False


def get_logger():
    """获取 logger，确保日志目录存在."""
    global _log_configured
    if not _log_configured:
        QUEUE_DIR.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger = logging.getLogger("bili_queue")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        logger.propagate = False
        _log_configured = True
    return logging.getLogger("bili_queue")


logger = get_logger()

# ---------------------------------------------------------------------------
# 颜色（终端输出用）
# ---------------------------------------------------------------------------
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
RED = "\033[0;31m"
BLUE = "\033[0;34m"
NC = "\033[0m"


def _echo(color, symbol, msg):
    """带颜色输出到终端."""
    print(f"{color}{symbol}{NC} {msg}")


# ---------------------------------------------------------------------------
# 任务存储
# ---------------------------------------------------------------------------
class TaskStore:
    """基于 JSON 文件的任务持久化存储."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._tasks: dict = {}
        self._load()

    # -- 读写 ---------------------------------------------------------------
    def _load(self):
        try:
            if self.path.exists():
                with open(self.path, encoding="utf-8") as f:
                    self._tasks = json.load(f)
            else:
                self._tasks = {}
        except (json.JSONDecodeError, OSError):
            self._tasks = {}

    def _save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._tasks, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    # -- CRUD ---------------------------------------------------------------
    def add(self, task_id: str, url: str, model: str):
        self._tasks[task_id] = {
            "url": url,
            "model": model,
            "status": "pending",
            "retries": 0,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "started_at": None,
            "completed_at": None,
            "last_error": None,
        }
        self._save()

    def get(self, task_id: str) -> dict | None:
        return self._tasks.get(task_id)

    def update(self, task_id: str, **kwargs):
        if task_id in self._tasks:
            self._tasks[task_id].update(kwargs)
            self._save()

    def remove(self, task_id: str):
        self._tasks.pop(task_id, None)
        self._save()

    # -- 查询 ---------------------------------------------------------------
    def list_by_status(self, status: str | None = None) -> dict:
        if status:
            return {k: v for k, v in self._tasks.items() if v["status"] == status}
        return dict(self._tasks)

    def count_by_status(self, status: str) -> int:
        return sum(1 for v in self._tasks.values() if v["status"] == status)

    def next_pending(self) -> str | None:
        """取最早创建的 pending 任务 ID."""
        pending = [(tid, t) for tid, t in self._tasks.items() if t["status"] == "pending"]
        if not pending:
            return None
        pending.sort(key=lambda x: x[1].get("created_at", ""))
        return pending[0][0]

    def running_task(self) -> str | None:
        """取当前 running 任务 ID."""
        for tid, t in self._tasks.items():
            if t["status"] == "running":
                return tid
        return None


# ---------------------------------------------------------------------------
# 文件锁
# ---------------------------------------------------------------------------
class FileLock:
    """基于 mkdir 原子操作的文件锁（与 shell 版兼容，进程崩溃自动释放）."""

    def __init__(self, path: Path):
        self.path = path

    def acquire(self, timeout: float = 30.0) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        start = time.time()
        while time.time() - start < timeout:
            try:
                self.path.mkdir(mode=0o700, exist_ok=False)
                return True
            except FileExistsError:
                time.sleep(0.5)
        return False

    def release(self):
        try:
            self.path.rmdir()
        except OSError:
            pass

    def __enter__(self):
        if not self.acquire():
            raise TimeoutError(f"无法获取锁: {self.path}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


# ---------------------------------------------------------------------------
# CPU 使用率
# ---------------------------------------------------------------------------
def get_cpu_usage() -> int:
    """读取 /proc/stat 计算 CPU 使用率（纯标准库，无需 psutil）."""
    try:
        with open("/proc/stat") as f:
            fields = f.readline().split()
        idle1 = int(fields[4]) + int(fields[5])  # idle + iowait
        total1 = sum(int(v) for v in fields[1:])
        time.sleep(1)
        with open("/proc/stat") as f:
            fields = f.readline().split()
        idle2 = int(fields[4]) + int(fields[5])
        total2 = sum(int(v) for v in fields[1:])
        delta_total = total2 - total1
        delta_idle = idle2 - idle1
        if delta_total <= 0:
            return 0
        return int(100 * (delta_total - delta_idle) / delta_total)
    except (OSError, IndexError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# 转录执行
# ---------------------------------------------------------------------------
def run_transcription(url: str, model: str, task_id: str) -> dict:
    """执行完整转录流程，返回结果字典.

    返回:
        {"success": True, "bv": "...", "title": "...", "transcript": "...", "audio": "..."}
        {"success": False, "error": "..."}
    """
    # 1. 解析 BV ID
    try:
        bvid = extract_bvid(url)
    except Exception as e:
        return {"success": False, "error": f"URL 解析失败: {e}"}

    # 2. 获取视频信息
    title = bvid
    duration = 0
    try:
        info = get_video_info(bvid)
        title = info.get("title", bvid)
        duration = info.get("duration", 0)
    except Exception:
        pass

    # 3. 创建安全文件名
    safe_title = title[:20].replace("/", "_").replace(" ", "_")
    filename = f"{bvid}_{safe_title}"

    # 4. 确保输出目录
    audio_dir = OUTPUT_DIR / "audio"
    transcript_dir = OUTPUT_DIR / "transcripts"
    audio_dir.mkdir(parents=True, exist_ok=True)
    transcript_dir.mkdir(parents=True, exist_ok=True)

    # 5. 保存链接信息
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    link_info = (
        f"视频链接: https://www.bilibili.com/video/{bvid}/\n"
        f"BV号: {bvid}\n"
        f"标题: {title}\n"
        f"时长: {duration}秒\n"
        f"转录模型: {model}\n"
        f"转录时间: {now}\n"
    )
    (transcript_dir / f"{filename}_link.txt").write_text(link_info, encoding="utf-8")

    # 6. 执行转录（三级降级）
    audio_path = audio_dir / f"{filename}.m4s"
    transcript_path = transcript_dir / f"{filename}.txt"

    # 获取 CID
    try:
        cid, _part_title, _total_pages = get_cid(bvid, 0)
    except Exception as e:
        return {"success": False, "error": f"获取 CID 失败: {e}"}

    subtitles = []

    # 第 1/2 级：CC/AI 字幕
    try:
        sub_list = get_subtitle_url(bvid, cid, "")
        if sub_list:
            cc_subs = [s for s in sub_list if not s.get("lan", "").startswith("ai")]
            ai_subs = [s for s in sub_list if s.get("lan", "").startswith("ai")]
            for sub in cc_subs + ai_subs:
                try:
                    sub_data = download_subtitle_json(sub["subtitle_url"])
                    body = sub_data.get("body", [])
                    if body:
                        subtitles = body
                        break
                except urllib.error.URLError:
                    continue
    except Exception:
        pass

    # 第 3 级：Whisper 降级
    if not subtitles:
        try:
            audio_url = get_audio_url(bvid, cid)
            if audio_url:
                referer = f"https://www.bilibili.com/video/{bvid}/"
                download_audio(audio_url, str(audio_path), referer)
                result = whisper_transcribe(str(audio_path), "zh", model)
                if result:
                    subtitles = result
        except Exception as e:
            return {"success": False, "error": f"Whisper 转录失败: {e}"}

    if not subtitles:
        return {"success": False, "error": "该视频没有可用字幕"}

    # 7. 写入文稿
    lines = [item.get("content", "") for item in subtitles]
    transcript_path.write_text("\n".join(lines), encoding="utf-8")

    return {
        "success": True,
        "bv": bvid,
        "title": title,
        "transcript": str(transcript_path),
        "audio": str(audio_path) if audio_path.exists() else None,
        "lines": len(lines),
    }


# ---------------------------------------------------------------------------
# 命令实现
# ---------------------------------------------------------------------------
def cmd_add(args):
    """添加任务到队列."""
    url = args.url
    model = args.model

    # 验证模型
    valid_models = {"tiny", "base", "small", "medium", "large-v3"}
    if model not in valid_models:
        print(f"{RED}✗{NC} 无效模型 '{model}'，可选: {'/'.join(sorted(valid_models))}")
        sys.exit(1)

    store = TaskStore(TASKS_FILE)
    bv = "unknown"
    try:
        bv = extract_bvid(url)
    except Exception:
        print(f"{YELLOW}⚠ 警告: 无法解析 BV ID，但任务仍会加入队列{NC}")

    task_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{bv}"
    store.add(task_id, url, model)

    print(f"{GREEN}✓{NC} 任务已加入队列: {BLUE}{task_id}{NC}")
    print(f"  URL:   {url}")
    print(f"  Model: {model}")
    print(f"  BV:    {bv}")

    # 安装 cron 提示
    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5)
        if str(Path(__file__).resolve()) not in result.stdout:
            print(f"\n{YELLOW}💡 提示: 尚未安装 cron 调度，运行以下命令启用自动处理:{NC}")
            print(f"  {sys.executable} {Path(__file__).resolve()} install-cron")
    except Exception:
        pass


def cmd_cron(_args):
    """定时处理队列（由 cron 每 10 分钟调用一次）."""
    store = TaskStore(TASKS_FILE)
    lock = FileLock(LOCK_FILE)

    if not lock.acquire():
        logger.info("无法获取锁，另一个 cron 进程正在运行")
        return

    try:
        # 检查是否有运行中的任务
        running_id = store.running_task()
        if running_id:
            task = store.get(running_id)
            if task and task.get("started_at"):
                # 检查是否超时
                try:
                    start = datetime.strptime(task["started_at"], "%Y-%m-%d %H:%M:%S")
                    elapsed = (datetime.now() - start).total_seconds()
                    if elapsed > TIMEOUT:
                        retries = task.get("retries", 0) + 1
                        logger.warning(
                            "任务 %s 运行超时（%.0f秒），重试 %d/%d", running_id, elapsed, retries, MAX_RETRIES
                        )
                        if retries >= MAX_RETRIES:
                            store.update(running_id, status="failed", last_error="超时", retries=retries)
                            logger.error("任务 %s 超时，已达最大重试次数", running_id)
                        else:
                            store.update(running_id, status="pending", retries=retries, started_at=None)
                            logger.info("任务 %s 超时，放回队列（重试 %d/%d）", running_id, retries, MAX_RETRIES)
                    else:
                        # 正常运行中，跳过
                        return
                except ValueError:
                    pass
            else:
                # 运行中但无 started_at，视为僵死
                logger.warning("任务 %s 状态异常，重置为 pending", running_id)
                store.update(running_id, status="pending", started_at=None)

        # 取下一个待处理任务
        task_id = store.next_pending()
        if not task_id:
            return

        task = store.get(task_id)
        if not task:
            return

        # CPU 检查
        cpu = get_cpu_usage()
        if cpu > CPU_THRESHOLD:
            logger.info("CPU %d%% > %d%%，跳过任务 %s", cpu, CPU_THRESHOLD, task_id)
            return

        url = task["url"]
        model = task.get("model", "small")

        # 标记运行中
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        store.update(task_id, status="running", started_at=now)

    finally:
        lock.release()

    # 释放锁后执行转录（不阻塞其他 cron 进程）
    logger.info("▶ 开始处理: %s  URL: %s  Model: %s", task_id, url, model)

    result = run_transcription(url, model, task_id)

    # 重新获取锁更新状态
    lock.acquire(timeout=60)
    try:
        if result["success"]:
            store.update(
                task_id,
                status="done",
                completed_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
            logger.info("✓ 完成: %s  (%s 行)", task_id, result.get("lines", 0))
        else:
            task = store.get(task_id) or {}
            retries = task.get("retries", 0) + 1
            error = result.get("error", "未知错误")

            if retries >= MAX_RETRIES:
                store.update(task_id, status="failed", retries=retries, last_error=error)
                logger.error("✗ 失败（已达最大重试次数）: %s  %s", task_id, error)
            else:
                store.update(task_id, status="pending", retries=retries, last_error=error, started_at=None)
                logger.info("↻ 失败，放回队列（重试 %d/%d）: %s  %s", retries, MAX_RETRIES, task_id, error)
    finally:
        lock.release()


def cmd_status(_args):
    """查看队列状态."""
    store = TaskStore(TASKS_FILE)

    pending = store.count_by_status("pending")
    running = store.count_by_status("running")
    done = store.count_by_status("done")
    failed = store.count_by_status("failed")
    cpu = get_cpu_usage()

    print("=" * 40)
    print("  Bilibili 转录队列状态")
    print("=" * 40)
    print()

    # 正在运行
    running_id = store.running_task()
    if running_id:
        task = store.get(running_id)
        if task is not None:
            print(f"  ▶ {GREEN}正在运行{NC}")
            print(f"    ID:     {running_id}")
            print(f"    URL:    {task['url']}")
            print(f"    Model:  {task['model']}")
            started_at = task.get("started_at")
            if started_at:
                try:
                    start = datetime.strptime(started_at, "%Y-%m-%d %H:%M:%S")
                    elapsed = (datetime.now() - start).total_seconds()
                    if elapsed > 60:
                        print(f"    已运行: {int(elapsed // 60)} 分钟")
                    else:
                        print(f"    已运行: {int(elapsed)} 秒")
                except ValueError:
                    pass
    else:
        print(f"  ▶ {YELLOW}当前无运行中的任务{NC}")
    print()

    # 统计
    print("  📊 统计")
    print(f"    {BLUE}待处理:{NC} {pending}")
    print(f"    {GREEN}已完成:{NC} {done}")
    print(f"    {RED}失败:{NC}   {failed}")
    print()

    # CPU
    cpu_color = GREEN if cpu <= CPU_THRESHOLD else RED
    print(f"  ⚡ CPU: {cpu_color}{cpu}%{NC} (阈值 {CPU_THRESHOLD}%)")
    print()

    # 最近日志
    if LOG_FILE.exists():
        try:
            with open(LOG_FILE, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            last_lines = lines[-5:] if len(lines) > 5 else lines
            print("  📝 最近日志:")
            for line in last_lines:
                print(f"    {line.rstrip()}")
        except OSError:
            pass
        print()

    # 提示
    if pending > 0 and not running_id:
        if cpu <= CPU_THRESHOLD:
            print(f"  {GREEN}💡 CPU 空闲，队列有 {pending} 个任务待处理{NC}")
            print("     cron 将在 1 分钟内自动开始处理")
        else:
            print(f"  {YELLOW}💡 队列有 {pending} 个任务，CPU {cpu}% 繁忙，等待中...{NC}")


def cmd_list(args):
    """列出任务."""
    store = TaskStore(TASKS_FILE)
    filter_status = args.status

    statuses = {
        "pending": ("待处理", BLUE),
        "running": ("运行中", GREEN),
        "done": ("已完成", GREEN),
        "failed": ("失败", RED),
    }

    if filter_status:
        target = {filter_status: statuses.get(filter_status, ("", ""))}
    else:
        target = statuses

    for st, (label, color) in target.items():
        tasks = store.list_by_status(st)
        if not tasks:
            continue
        print(f"{color}{label}{NC}:")
        for tid, t in sorted(tasks.items(), key=lambda x: x[1].get("created_at", "")):
            if st == "done":
                print(f"  ✓ {tid}")
                print(f"    URL: {t['url']} | Model: {t['model']}")
            elif st == "failed":
                err = (t.get("last_error") or "")[:80]
                print(f"  ✗ {tid} (重试 {t.get('retries', 0)}/{MAX_RETRIES})")
                print(f"    URL: {t['url']} | Model: {t['model']} | 错误: {err}")
            elif st == "running":
                print(f"  ▶ {tid}")
                print(f"    URL: {t['url']} | Model: {t['model']} | 开始: {t.get('started_at', '')}")
            else:
                print(f"  ○ {tid}")
                print(f"    URL: {t['url']} | Model: {t['model']} | 重试: {t.get('retries', 0)}/{MAX_RETRIES}")
        print()


def cmd_retry(args):
    """重试失败任务."""
    store = TaskStore(TASKS_FILE)
    task = store.get(args.task_id)
    if task is None:
        print(f"{RED}✗{NC} 未找到任务 {args.task_id}")
        print(f"使用 '{sys.argv[0]} list failed' 查看失败任务")
        sys.exit(1)
    if task["status"] != "failed":
        print(f"{YELLOW}⚠ 任务 {args.task_id} 状态不是 failed（当前: {task['status']}）{NC}")
        sys.exit(1)
    store.update(args.task_id, status="pending", retries=0, last_error=None, started_at=None)
    print(f"{GREEN}✓{NC} 任务 {args.task_id} 已放回队列，准备重试")


def cmd_remove(args):
    """删除任务."""
    store = TaskStore(TASKS_FILE)
    task = store.get(args.task_id)
    if task is None:
        print(f"{RED}✗{NC} 未找到任务 {args.task_id}")
        sys.exit(1)
    store.remove(args.task_id)
    print(f"{GREEN}✓{NC} 已删除任务 {args.task_id}")


def cmd_cancel(_args):
    """取消当前运行的任务."""
    store = TaskStore(TASKS_FILE)
    running_id = store.running_task()
    if not running_id:
        print("当前没有运行中的任务")
        return

    task = store.get(running_id)
    if task is None:
        print(f"{RED}✗{NC} 未找到任务 {running_id}")
        return
    url = task["url"]
    print(f"{YELLOW}⚠ 正在取消任务: {running_id}{NC}")
    print(f"  URL: {url}")

    # 杀掉关联的转录进程
    subprocess.run(
        ["pkill", "-f", f"fetch_transcript.py.*{url}"],
        capture_output=True,
        timeout=5,
    )

    store.update(running_id, status="pending", retries=0, last_error="cancelled", started_at=None)
    print(f"{GREEN}✓{NC} 任务已取消并放回队列")


def cmd_clear(args):
    """清空队列."""
    store = TaskStore(TASKS_FILE)
    target = args.target

    if target == "pending":
        for tid in list(store.list_by_status("pending")):
            store.remove(tid)
        print(f"{GREEN}✓{NC} 已清空待处理队列")
    elif target == "failed":
        for tid in list(store.list_by_status("failed")):
            store.remove(tid)
        print(f"{GREEN}✓{NC} 已清空失败任务")
    else:
        pending = store.count_by_status("pending")
        failed = store.count_by_status("failed")
        total = pending + failed
        if total == 0:
            print("队列已空")
            return
        print(f"{YELLOW}⚠ 将删除 {total} 个任务（{pending} 待处理 + {failed} 失败）{NC}")
        print("确认？(y/N): ", end="", flush=True)
        confirm = input().strip().lower()
        if confirm == "y":
            for tid in list(store.list_by_status("pending")):
                store.remove(tid)
            for tid in list(store.list_by_status("failed")):
                store.remove(tid)
            print(f"{GREEN}✓{NC} 已清空队列")
        else:
            print("已取消")


def cmd_install_cron(_args):
    """安装 crontab."""
    script_path = Path(__file__).resolve()
    cron_entry = f"*/10 * * * * {sys.executable} {script_path} cron >> {LOG_FILE} 2>&1"

    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5)
        existing = result.stdout.splitlines() if result.returncode == 0 else []
    except FileNotFoundError:
        print(f"{RED}✗{NC} 未找到 crontab 命令")
        sys.exit(1)

    # 过滤已有条目
    new_lines = [l for l in existing if str(script_path) not in l]
    new_lines.append(cron_entry)

    content = "\n".join(new_lines) + "\n"
    result = subprocess.run(
        ["crontab", "-"],
        input=content,
        capture_output=True,
        text=True,
        timeout=5,
    )

    if result.returncode == 0:
        print(f"{GREEN}✓{NC} crontab 已安装")
        print(f"  条目: {cron_entry}")
        print(f"  日志: {LOG_FILE}")
        print()
        print(f"{YELLOW}💡 提示:{NC} cron 将每 10 分钟检查一次队列")
        print("  CPU 空闲时 → 自动开始处理")
        print("  CPU 繁忙时 → 跳过，等待下次检查")
        print("  可以在任意时间通过 'add <URL>' 添加任务")
    else:
        print(f"{RED}✗{NC} 安装 crontab 失败: {result.stderr}")
        sys.exit(1)


def cmd_uninstall_cron(_args):
    """卸载 crontab."""
    script_path = Path(__file__).resolve()

    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            print(f"{YELLOW}⚠ 未找到 crontab 条目{NC}")
            return
        existing = result.stdout.splitlines()
    except FileNotFoundError:
        print(f"{YELLOW}⚠ 未找到 crontab 命令{NC}")
        return

    new_lines = [l for l in existing if str(script_path) not in l]
    if len(new_lines) == len(existing):
        print(f"{YELLOW}⚠ 未找到相关的 crontab 条目{NC}")
        return

    content = "\n".join(new_lines) + "\n"
    subprocess.run(["crontab", "-"], input=content, capture_output=True, text=True, timeout=5)
    print(f"{GREEN}✓{NC} crontab 已卸载")


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Bilibili 转录任务队列管理")
    sub = parser.add_subparsers(dest="command", help="可用命令")

    # add
    p_add = sub.add_parser("add", help="添加任务到队列")
    p_add.add_argument("url", help="B 站视频链接或 BV ID")
    p_add.add_argument(
        "model",
        nargs="?",
        default="small",
        choices=["tiny", "base", "small", "medium", "large-v3"],
        help="模型大小（默认: small）",
    )

    # cron
    sub.add_parser("cron", help="定时处理队列（由 cron 调用）")

    # status
    sub.add_parser("status", help="查看队列状态")

    # list
    p_list = sub.add_parser("list", help="列出任务")
    p_list.add_argument(
        "status",
        nargs="?",
        default=None,
        choices=["pending", "running", "done", "failed"],
        help="按状态过滤",
    )

    # retry
    p_retry = sub.add_parser("retry", help="重试失败任务")
    p_retry.add_argument("task_id", help="任务 ID")

    # remove
    p_remove = sub.add_parser("remove", help="删除任务")
    p_remove.add_argument("task_id", help="任务 ID")

    # cancel
    sub.add_parser("cancel", help="取消当前运行的任务")

    # clear
    p_clear = sub.add_parser("clear", help="清空队列")
    p_clear.add_argument(
        "target",
        nargs="?",
        default=None,
        choices=["pending", "failed"],
        help="清空指定类型（默认: 提示确认）",
    )

    # install-cron
    sub.add_parser("install-cron", help="安装 crontab")

    # uninstall-cron
    sub.add_parser("uninstall-cron", help="卸载 crontab")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    cmd_map = {
        "add": cmd_add,
        "cron": cmd_cron,
        "status": cmd_status,
        "list": cmd_list,
        "retry": cmd_retry,
        "remove": cmd_remove,
        "cancel": cmd_cancel,
        "clear": cmd_clear,
        "install-cron": cmd_install_cron,
        "uninstall-cron": cmd_uninstall_cron,
    }
    cmd_map[args.command](args)


# ---------------------------------------------------------------------------
# 兼容入口（供 fetch_transcript.py / pyproject.toml 调用）
# ---------------------------------------------------------------------------
def cli_main():
    """命令行转录入口，与旧 main.py 接口兼容."""
    parser = argparse.ArgumentParser(description="获取 B 站视频字幕")
    parser.add_argument("url", help="B 站视频链接或 BV ID")
    parser.add_argument("--text-only", action="store_true", help="仅输出纯文本")
    parser.add_argument("--timestamps", action="store_true", help="包含时间戳")
    parser.add_argument("--page", type=int, default=0, help="分 P 序号（从 0 开始）")
    parser.add_argument("--whisper", action="store_true", help="强制使用 Whisper 降级")
    parser.add_argument("--cookie", default="", help="B 站登录 Cookie")
    parser.add_argument("--json", action="store_true", help="输出原始 JSON")
    parser.add_argument("--language", default="zh", help="Whisper 语言提示（默认: zh）")
    parser.add_argument("--model", default="small", help="Whisper 模型大小")
    parser.add_argument("--save-audio", default="", help="保存音频文件到指定路径")
    args = parser.parse_args()

    # 复用 run_transcription 获取转录结果
    result = run_transcription(args.url, args.model, "cli")
    if not result["success"]:
        print(result["error"], file=sys.stderr)
        sys.exit(1)

    # 读回文稿
    transcript_path = result.get("transcript")
    if transcript_path:
        text = Path(transcript_path).read_text(encoding="utf-8")
        print(text)


if __name__ == "__main__":
    main()
