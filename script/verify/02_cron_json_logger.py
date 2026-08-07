#!/usr/bin/env python3
"""验证 cron 空循环能写入 cron_start/cron_end."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from src.core.queue_store import JsonLogger

# 读取当前日志行数
log_path = JsonLogger.path
if log_path.exists():
    with open(log_path) as f:
        before_count = len(f.readlines())
else:
    before_count = 0

# 触发空 cron（无任务时）
import subprocess
result = subprocess.run(
    [sys.executable, "src/cli/bili_queue.py", "cron"],
    capture_output=True, text=True
)
print(f"cron exit: {result.returncode}")

# 读取新日志
with open(log_path) as f:
    lines = f.readlines()

new_lines = lines[before_count:]
found_start = any('"cron_start"' in l for l in new_lines)
found_end = any('"cron_end"' in l for l in new_lines)

assert found_start, f"缺少 cron_start 事件，日志: {new_lines}"
assert found_end, f"缺少 cron_end 事件，日志: {new_lines}"

# 验证 JSON 格式
for line in new_lines:
    event = json.loads(line)
    assert "t" in event
    assert "e" in event

print("✅ cron 结构化日志验证通过")