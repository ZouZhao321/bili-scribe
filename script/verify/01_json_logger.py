#!/usr/bin/env python3
"""验证 JsonLogger 能正确写入结构化日志."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from src.core.queue_store import JsonLogger

# 1. 写入 3 条事件
log = JsonLogger()
log.write("cron_start", pid=12345, lock="acquired")
log.write("task_start", id="BV1test", model="tiny", url="https://www.bilibili.com/video/BV1test", mem_before=1200, cpu_before=23)
log.write("cron_end", pid=12345, dur_s=0.5)

# 2. 读取并验证
with open(JsonLogger.path) as f:
    lines = f.readlines()

assert len(lines) >= 3, f"期望至少 3 行，实际 {len(lines)}"

for i, line in enumerate(lines[-3:]):
    event = json.loads(line)
    assert "t" in event, f"第 {i} 行缺少 t 字段"
    assert "e" in event, f"第 {i} 行缺少 e 字段"

# 3. 验证字段值
events = [json.loads(l) for l in lines[-3:]]
assert events[0]["e"] == "cron_start"
assert events[1]["e"] == "task_start"
assert events[1]["id"] == "BV1test"
assert events[1]["model"] == "tiny"
assert events[2]["e"] == "cron_end"

print("✅ JsonLogger 验证通过")