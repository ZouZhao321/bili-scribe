#!/usr/bin/env bash
# 验证阶段一完整事件链
set -e

cd "$(dirname "$0")/../.."

# 添加测试任务
python3 -m src.cli.main queue add "BV1EZ4y1d7xC" tiny

# 触发 cron
python3 -m src.cli.main queue cron

# 验证事件链
python3 -c "
import json
from pathlib import Path
log_path = Path.home() / '.queue' / 'cron.jsonl'
with open(log_path) as f:
    events = [json.loads(l) for l in f]
events = [e for e in events if e.get('e') in ('cron_start','task_start','task_end','cron_end')]
event_names = [e['e'] for e in events]
assert 'cron_start' in event_names, f'缺少 cron_start: {event_names}'
assert 'task_start' in event_names, f'缺少 task_start: {event_names}'
assert 'task_end' in event_names, f'缺少 task_end: {event_names}'
print(f'✅ 阶段一验证通过: {event_names}')
"