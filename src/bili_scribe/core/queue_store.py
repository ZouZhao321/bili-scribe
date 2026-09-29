"""Bilibili 转录任务队列 — 持久化存储 + 文件锁 + CPU 检测.

提供队列存储、文件锁、CPU 使用率检测等基础设施，
供 CLI 入口和 cron 调度模块使用。
"""

import json
import logging
import time
from contextlib import suppress
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
OPERATIONS_LOG = QUEUE_DIR / "operations.log"

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
# 结构化日志（JSON Lines）
# ---------------------------------------------------------------------------
JSONL_FILE = QUEUE_DIR / "cron.jsonl"


class JsonLogger:
    """结构化日志 — 写入 JSON Lines 格式到 ~/.queue/cron.jsonl.

    每行一个 JSON 对象，固定字段:
      t — ISO 格式时间戳
      e — 事件名
    其他字段按事件类型不同。

    事件列表:
      cron_start  — cron 进程启动，字段: pid, lock
      cron_skip   — cron 跳过，字段: reason
      cron_end    — cron 结束，字段: pid, dur_s
      task_start  — 任务开始，字段: id, model, url, mem_before, cpu_before
      task_end    — 任务完成，字段: id, dur_s, seg, avg_p, mem_peak, mem_after, cpu_avg
      task_skip   — 任务跳过，字段: id, reason, mem, cpu, model
      task_retry  — 任务重试，字段: id, retry, error
      task_fail   — 任务失败，字段: id, error
    """

    path = JSONL_FILE

    @classmethod
    def write(cls, event: str, **kwargs):
        """写入一条结构化日志。

        参数:
            event: 事件名（如 cron_start, task_end）
            **kwargs: 事件相关字段
        """
        try:
            cls.path.parent.mkdir(parents=True, exist_ok=True)
            record = {"t": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "e": event, **kwargs}
            with open(cls.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass


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
        # 目录可能已被清理/占用，静默忽略即可
        with suppress(OSError):
            self.path.rmdir()

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
# 容器内存检测
# ---------------------------------------------------------------------------
# cgroup v2 路径，cgroup v1 路径用于旧内核
CGROUP_V2_LIMIT = "/sys/fs/cgroup/memory.max"
CGROUP_V2_USAGE = "/sys/fs/cgroup/memory.current"
CGROUP_V2_EVENTS = "/sys/fs/cgroup/memory.events"
CGROUP_V1_LIMIT = "/sys/fs/cgroup/memory/memory.limit_in_bytes"
CGROUP_V1_USAGE = "/sys/fs/cgroup/memory/memory.usage_in_bytes"
CGROUP_V1_EVENTS = "/sys/fs/cgroup/memory/memory.oom_control"

# cgroup v1 用该量级的数值表示「无限制」
_NO_LIMIT_THRESHOLD = 1 << 60


def _read_int_file(path: str) -> int | None:
    """读取只包含一个整数的文件.

    参数：
        path: 文件路径.

    返回：
        文件内容对应的整数；文件不存在、内容为 cgroup v2 的 "max"
        或无法解析时返回 None.
    """
    try:
        with open(path) as f:
            raw = f.read().strip()
    except OSError:
        return None
    if raw == "max":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _read_cgroup_event(path: str, key: str) -> int:
    """从 cgroup 计数文件中读取指定字段.

    参数：
        path: cgroup 计数文件路径.
        key: 字段名称，如 "oom_kill".

    返回：
        字段数值，文件不存在或字段缺失时返回 0.
    """
    try:
        with open(path) as f:
            lines = f.readlines()
    except OSError:
        return 0
    for line in lines:
        fields = line.split()
        if len(fields) == 2 and fields[0] == key:
            try:
                return int(fields[1])
            except ValueError:
                return 0
    return 0


def get_cgroup_memory_limit_mb() -> int | None:
    """读取容器 cgroup 的内存限额（MB）.

    返回：
        限额 MB；不在容器内运行或限额为「无限制」时返回 None.
    """
    limit_bytes = _read_int_file(CGROUP_V2_LIMIT)
    if limit_bytes is None:
        limit_bytes = _read_int_file(CGROUP_V1_LIMIT)
    if limit_bytes is None or limit_bytes >= _NO_LIMIT_THRESHOLD:
        return None
    return limit_bytes // (1024 * 1024)


def get_cgroup_memory_usage_mb() -> int | None:
    """读取容器 cgroup 的当前内存用量（MB）.

    返回：
        用量 MB，无法读取时返回 None.
    """
    usage_bytes = _read_int_file(CGROUP_V2_USAGE)
    if usage_bytes is None:
        usage_bytes = _read_int_file(CGROUP_V1_USAGE)
    if usage_bytes is None:
        return None
    return usage_bytes // (1024 * 1024)


def get_oom_kill_count() -> int:
    """读取容器 cgroup 累计记录的进程被内核 OOM 击杀次数.

    计数在容器生命周期内持续累加，容器被重建后归零.

    返回：
        累计击杀次数；不在容器内运行或无法读取时返回 0.
    """
    count = _read_cgroup_event(CGROUP_V2_EVENTS, "oom_kill")
    if count:
        return count
    return _read_cgroup_event(CGROUP_V1_EVENTS, "oom_kill")


def get_available_memory_mb() -> int:
    """获取本次转录可用的内存（MB）.

    在容器内以 cgroup 限额减去当前用量为准：/proc/meminfo 的 MemAvailable
    反映的是宿主机（或虚拟机）的内存，与容器限额无关. 不在容器内运行时
    退回 /proc/meminfo.

    返回：
        可用内存 MB.
    """
    limit_mb = get_cgroup_memory_limit_mb()
    usage_mb = get_cgroup_memory_usage_mb()
    if limit_mb is not None and usage_mb is not None:
        return max(0, limit_mb - usage_mb)

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
