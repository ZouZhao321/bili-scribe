"""Bilibili 转录任务队列 — 持久化存储 + 文件锁 + CPU 检测.

提供队列存储、文件锁、CPU 使用率检测等基础设施，
供 CLI 入口和 cron 调度模块使用。
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path

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
MEMORY_THRESHOLD = 0.90  # 可用内存低于模型需求的 90% 时跳过

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
# 模型内存需求（MB）
# ---------------------------------------------------------------------------
MODEL_MEMORY_REQUIREMENTS = {
    "tiny": 500,  # MB，实际模型 75MB + 开销
    "base": 1000,  # MB，实际模型 141MB + 开销
    "small": 2000,  # MB，实际模型 464MB + 开销
    "medium": 3500,  # MB，实际模型 1.5GB + 开销（RSS ~3GB）
    "large-v3": 5500,  # MB，实际模型 2.9GB + 开销
}


# ---------------------------------------------------------------------------
# 可用内存检测
# ---------------------------------------------------------------------------
def get_available_memory_mb() -> int:
    """读取 /proc/meminfo 获取可用内存（MB）."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    kb = int(line.split()[1])
                    return kb // 1024
    except (OSError, IndexError, ValueError):
        pass
    return 0


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
