#!/usr/bin/env python3
"""Bilibili 转录任务队列 — CLI 入口 + cron 定时调度.

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
    - 可用内存 ≥ 模型需求的 90% → 自动取任务执行
    - 可用内存 < 模型需求的 90% → 跳过，避免 OOM
    - 可用内存 ≥ 模型需求的 90% → 自动取任务执行
    - 可用内存 < 模型需求的 90% → 跳过，避免 OOM
    - 失败自动重试，最多 3 次
    - 任务运行超 6 小时视为僵死，放回队列重试
"""

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# 项目路径
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.bilibili import extract_bvid  # noqa: E402
from src.core.queue_store import (  # noqa: E402
    BLUE,
    CPU_THRESHOLD,
    GREEN,
    LOG_FILE,
    MAX_RETRIES,
    MEMORY_THRESHOLD,
    MODEL_MEMORY_REQUIREMENTS,
    NC,
    RED,
    YELLOW,
    FileLock,
    JsonLogger,
    TaskStore,
    get_available_memory_mb,
    get_cpu_usage,
    logger,
)
from src.core.runner import TIMEOUT, run_transcription  # noqa: E402


# ---------------------------------------------------------------------------
# Git 临时分支操作
# ---------------------------------------------------------------------------
def git_commit_and_push(branch_name: str, task_id: str, result: dict) -> None:
    """在临时分支上提交转录输出并推送到远端.

    创建 transcribe/BVxxx 分支，添加输出文件，提交并推送。
    失败时记录日志但不会抛出异常。
    """
    bv = result.get("bv", "")
    title = result.get("title", "")[:60]
    commit_msg = f"feat(transcribe): {bv} {title}" if title else f"feat(transcribe): {task_id}"
    output_dir = PROJECT_ROOT / "out"

    try:
        # 确保在 main 上
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=PROJECT_ROOT, capture_output=True, timeout=30,
        )

        # 若本地已有同名分支则删除
        branch_check = subprocess.run(
            ["git", "branch", "--list", branch_name],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=10,
        )
        if branch_name in branch_check.stdout:
            subprocess.run(
                ["git", "branch", "-D", branch_name],
                cwd=PROJECT_ROOT, capture_output=True, timeout=15,
            )

        # 创建临时分支
        subprocess.run(
            ["git", "checkout", "-b", branch_name],
            cwd=PROJECT_ROOT, check=True, capture_output=True, timeout=30,
        )

        # 查找并强制添加输出目录
        out_pattern = f"{bv}_*" if bv else task_id
        matched = sorted(output_dir.glob(out_pattern))
        if matched:
            for p in matched:
                subprocess.run(
                    ["git", "add", "-f", str(p)],
                    cwd=PROJECT_ROOT, check=True, capture_output=True, timeout=30,
                )

        # 提交
        subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=PROJECT_ROOT, check=True, capture_output=True, timeout=30,
        )

        # 推送
        subprocess.run(
            ["git", "push", "origin", branch_name],
            cwd=PROJECT_ROOT, check=True, capture_output=True, timeout=60,
        )

        logger.info("Git 分支已推送: %s  %s", branch_name, commit_msg)

    except subprocess.CalledProcessError as e:
        logger.warning("Git 分支操作失败 (stderr): %s", e.stderr.decode() if e.stderr else str(e))
    except Exception as e:
        logger.warning("Git 分支操作异常: %s", e)
    finally:
        # 始终切回 main
        try:
            subprocess.run(
                ["git", "checkout", "main"],
                cwd=PROJECT_ROOT, capture_output=True, timeout=15,
            )
        except Exception:
            pass

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
LOCK_FILE = Path.home() / ".queue" / "queue.lock"
TASKS_FILE = Path.home() / ".queue" / "tasks.json"


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
    pid = os.getpid()
    cron_start_time = time.time()
    store = TaskStore(TASKS_FILE)
    lock = FileLock(LOCK_FILE)

    if not lock.acquire():
        logger.info("无法获取锁，另一个 cron 进程正在运行")
        JsonLogger.write("cron_skip", reason="lock_busy", pid=pid)
        return

    JsonLogger.write("cron_start", pid=pid, lock="acquired")

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
                        JsonLogger.write("cron_end", pid=pid, dur_s=round(time.time() - cron_start_time, 2))
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
            JsonLogger.write("cron_end", pid=pid, dur_s=round(time.time() - cron_start_time, 2))
            return

        task = store.get(task_id)
        if not task:
            return

        # CPU 检查
        cpu = get_cpu_usage()
        if cpu > CPU_THRESHOLD:
            logger.info("CPU %d%% > %d%%，跳过任务 %s", cpu, CPU_THRESHOLD, task_id)
            JsonLogger.write("task_skip", id=task_id, reason="cpu", mem=get_available_memory_mb(), cpu=cpu, model=task.get("model", "small"))
            JsonLogger.write("cron_end", pid=pid, dur_s=round(time.time() - cron_start_time, 2))
            return

        url = task["url"]
        model = task.get("model", "small")

        # 内存检查
        mem_avail = get_available_memory_mb()
        mem_required = MODEL_MEMORY_REQUIREMENTS.get(model, 2000)
        mem_needed = int(mem_required * MEMORY_THRESHOLD)
        if mem_avail < mem_needed:
            logger.info(
                "内存不足: 可用 %dMB < 需要 %dMB (模型 %s)，跳过任务 %s",
                mem_avail,
                mem_needed,
                model,
                task_id,
            )
            JsonLogger.write("task_skip", id=task_id, reason="mem", mem=mem_avail, cpu=cpu, model=model)
            JsonLogger.write("cron_end", pid=pid, dur_s=round(time.time() - cron_start_time, 2))
            return

        # 标记运行中
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        store.update(task_id, status="running", started_at=now)

    finally:
        lock.release()

    # 释放锁后执行转录（不阻塞其他 cron 进程）
    mem_before = get_available_memory_mb()
    cpu_before = get_cpu_usage()
    JsonLogger.write("task_start", id=task_id, model=model, url=url, mem_before=mem_before, cpu_before=cpu_before)
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
            dur_s = round(time.time() - cron_start_time, 2)
            mem_after = get_available_memory_mb()
            JsonLogger.write(
                "task_end",
                id=task_id,
                dur_s=dur_s,
                seg=result.get("lines", 0),
                avg_p=result.get("avg_prob", 0),
                mem_peak=mem_before - mem_after,
                mem_after=mem_after,
                cpu_avg=get_cpu_usage(),
            )
            logger.info("✓ 完成: %s  (%s 行)", task_id, result.get("lines", 0))

            # 转录成功 → 提交到临时 git 分支并推送
            branch_name = f"transcribe/{task_id}"
            git_commit_and_push(branch_name, task_id, result)
        else:
            task = store.get(task_id) or {}
            retries = task.get("retries", 0) + 1
            error = result.get("error", "未知错误")

            if retries >= MAX_RETRIES:
                store.update(task_id, status="failed", retries=retries, last_error=error)
                JsonLogger.write("task_fail", id=task_id, error=error)
                logger.error("✗ 失败（已达最大重试次数）: %s  %s", task_id, error)
            else:
                store.update(task_id, status="pending", retries=retries, last_error=error, started_at=None)
                JsonLogger.write("task_retry", id=task_id, retry=retries, error=error)
                logger.info("↻ 失败，放回队列（重试 %d/%d）: %s  %s", retries, MAX_RETRIES, task_id, error)
    finally:
        JsonLogger.write("cron_end", pid=pid, dur_s=round(time.time() - cron_start_time, 2))
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

    # 内存
    mem_avail = get_available_memory_mb()
    if running_id:
        running_task = store.get(running_id)
        model = running_task.get("model", "?") if running_task else "?"
        mem_req = MODEL_MEMORY_REQUIREMENTS.get(model, 0)
        mem_color = GREEN if mem_avail >= mem_req else RED
        print(
            f"  🧠 内存: 可用 {mem_avail}MB | 当前模型 {model} 需要 {mem_req}MB ({mem_color}{'充足' if mem_avail >= mem_req else '不足'}{NC})"
        )
    else:
        print(f"  🧠 内存: 可用 {mem_avail}MB")
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
        mem_ok = mem_avail >= MODEL_MEMORY_REQUIREMENTS.get("small", 2000)
        if cpu <= CPU_THRESHOLD and mem_ok:
            print(f"  {GREEN}💡 CPU 空闲 + 内存充足，队列有 {pending} 个任务待处理{NC}")
            print("     cron 将在 1 分钟内自动开始处理")
        elif cpu > CPU_THRESHOLD:
            print(f"  {YELLOW}💡 队列有 {pending} 个任务，CPU {cpu}% 繁忙，等待中...{NC}")
        else:
            print(f"  {RED}💡 队列有 {pending} 个任务，但内存不足 (可用 {mem_avail}MB)，等待中...{NC}")


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
        default="tiny",
        choices=["tiny", "base", "small", "medium", "large-v3"],
        help="模型大小（默认: tiny）",
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


if __name__ == "__main__":
    main()
