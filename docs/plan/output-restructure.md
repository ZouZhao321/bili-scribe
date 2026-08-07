---
title: 输出格式重构实施计划
status: draft
created: 2026-08-07
branch: feat/output-restructure
---

# 输出格式重构实施计划

```
main
│
└─ feat/output-restructure
   │
   ├─ 阶段一：结构化日志
   │  ├─ 📝 chore(queue): 新增 JSON Lines 结构化日志
   │  ├─ 📝 feat(queue): cron 流程接入结构化日志
   │  └─ 📝 阶段验收
   │
   ├─ 阶段二：新输出格式
   │  ├─ 📝 feat(transcriber): 转录结果返回置信度
   │  ├─ 📝 feat(runner): 输出新格式 转录文稿.txt + 视频信息.txt
   │  └─ 📝 feat(cli): 新增 transcript-to-srt 子命令
   │
   ├─ 阶段三：迁移旧数据
   │  ├─ 📝 feat(script): 迁移脚本
   │  └─ 📝 执行迁移
   │
   └─ 阶段四：启动队列
      ├─ 📝 chore(queue): 默认模型改为 tiny
      └─ 📝 等待 cron 自动调度
```

---

## 阶段一：结构化日志

### 📝 Commit: `chore(queue): 新增 JSON Lines 结构化日志`

**改动文件**：`src/core/queue_store.py`

---

#### 🔧 开发

**做什么**：
- 新增 `JsonLogger` 类，写入 `~/.queue/cron.jsonl`
- 每行一个 JSON 事件，固定字段：
  - `t` — ISO 格式时间戳（`2026-08-07T15:00:00`）
  - `e` — 事件名
  - 其他字段按事件类型不同
- 事件定义：

| 事件 | 字段 | 触发时机 |
|:----:|------|----------|
| `cron_start` | `pid, lock` | cron 进程开始，是否拿到锁 |
| `cron_skip` | `reason` | 锁被占用 / 已有任务在跑 / 无任务 |
| `cron_end` | `pid, dur_s` | cron 进程结束 |
| `task_start` | `id, model, url, mem_before, cpu_before` | 任务开始执行 |
| `task_end` | `id, dur_s, seg, avg_p, mem_peak, mem_after, cpu_avg` | 任务成功完成 |
| `task_skip` | `id, reason, mem, cpu, model` | CPU 忙或内存不足 |
| `task_retry` | `id, retry, error` | 失败重试 |
| `task_fail` | `id, error` | 最终失败 |

**不做什么**：
- 不修改现有 `cron.log` 文本日志（保留兼容）
- 不接入 cron 流程（只建类，不改调用）

---

#### ✅ 验收

**验收脚本**：`script/verify/01_json_logger.py`

```python
#!/usr/bin/env python3
"""验证 JsonLogger 能正确写入结构化日志"""
import sys, json
sys.path.insert(0, '.')
from src.core.queue_store import JsonLogger

# 1. 写入 3 条事件
log = JsonLogger()
log.write('cron_start', pid=12345, lock='acquired')
log.write('task_start', id='BV1test', model='tiny', url='https://bilibili.com/video/BV1test', mem_before=1200, cpu_before=23)
log.write('cron_end', pid=12345, dur_s=0.5)

# 2. 读取并验证
with open(JsonLogger.path) as f:
    lines = f.readlines()

assert len(lines) >= 3, f"期望至少 3 行，实际 {len(lines)}"

for i, line in enumerate(lines[-3:]):
    event = json.loads(line)
    assert 't' in event, f"第 {i} 行缺少 t 字段"
    assert 'e' in event, f"第 {i} 行缺少 e 字段"

print("✅ JsonLogger 验证通过")
```

**运行方式**：
```bash
pi -p "python3 script/verify/01_json_logger.py"
```

---

### 📝 Commit: `feat(queue): cron 流程接入结构化日志`

**改动文件**：`src/cli/bili_queue.py`

---

#### 🔧 开发

**做什么**：
- `cmd_cron()` 函数入口写 `cron_start`
- 出口写 `cron_end`（含总耗时）
- 任务开始前写 `task_start`（记录 `mem_before`, `cpu_before`）
- 任务完成后写 `task_end`（记录 `dur_s`, `seg`, `avg_p`, `mem_peak`, `cpu_avg`）
- 跳过时写 `task_skip`（含原因）
- 失败/重试时写 `task_retry` / `task_fail`

**不做什么**：
- 不改 `runner.py` 的转录逻辑
- 不改 `TaskStore` 的存储结构

---

#### ✅ 验收

**验收脚本**：`script/verify/02_cron_json_logger.py`

```python
#!/usr/bin/env python3
"""验证 cron 空循环能写入 cron_start/cron_end"""
import sys, json
sys.path.insert(0, '.')
from src.core.queue_store import JsonLogger

# 读取当前日志
with open(JsonLogger.path) as f:
    before = f.readlines()

# 触发空 cron（无任务时）
import subprocess
subprocess.run([sys.executable, 'src/cli/bili_queue.py', 'cron'], capture_output=True)

# 读取新日志
with open(JsonLogger.path) as f:
    after = f.readlines()

new_lines = after[len(before):]
found_start = any('"cron_start"' in l for l in new_lines)
found_end = any('"cron_end"' in l for l in new_lines)
assert found_start, "缺少 cron_start 事件"
assert found_end, "缺少 cron_end 事件"
print("✅ cron 结构化日志验证通过")
```

**运行方式**：
```bash
pi -p "python3 script/verify/02_cron_json_logger.py"
```

---

### 📝 阶段验收

**验收脚本**：`script/verify/03_phase1_complete.py`

```bash
#!/usr/bin/env bash
# 验证阶段一完整事件链
python3 src/cli/bili_queue.py add "BV1xx" tiny
python3 src/cli/bili_queue.py cron
python3 -c "
import json
with open('$HOME/.queue/cron.jsonl') as f:
    events = [json.loads(l) for l in f]
events = [e for e in events if e.get('e') in ('cron_start','task_start','task_end','cron_end')]
assert len(events) >= 3, f'事件链不完整: {[e[\"e\"] for e in events]}'
print(f'✅ 阶段一验证通过: {[e[\"e\"] for e in events]}')
"
```

**运行方式**：
```bash
pi -p "bash script/verify/03_phase1_complete.sh"
```

---

## 阶段二：新输出格式

### 📝 Commit: `feat(transcriber): 转录结果返回置信度`

**改动文件**：`src/core/transcriber.py`

---

#### 🔧 开发

**做什么**：
- `whisper_transcribe()` 返回的每段增加 `avg_logprob`、`no_speech_prob`
- 新增 `format_transcript()` 函数，输出新格式：

```
[说话人 A] [tiny] [0.82] 00:00:01,230 - 00:00:52,100
大家好，今天我们来聊聊网文写作。首先……
```

- 字段规则：
  - 说话人：暂时固定 `[说话人 A]`（后续 diarize 阶段改）
  - 模型：从参数传入
  - 置信度：`avg_logprob` 转为 0~1 区间，取两位小数
  - 时间戳：SRT 毫秒级精度 `HH:MM:SS,mmm`

**不做什么**：
- 不修改模型加载逻辑
- 不修改 `runner.py` 的写入逻辑
- 不做说话人区分（后续独立阶段）

---

#### ✅ 验收

**验收脚本**：`script/verify/04_transcript_format.py`

```python
#!/usr/bin/env python3
"""验证 format_transcript 输出格式正确"""
import sys, re
sys.path.insert(0, '.')
from src.core.transcriber import format_transcript

# 模拟 Whisper 返回数据
mock_segments = [
    {'from': 1.23, 'to': 5.10, 'content': '大家好', 'avg_logprob': -0.2, 'no_speech_prob': 0.01},
    {'from': 5.10, 'to': 10.50, 'content': '今天我们来聊聊', 'avg_logprob': -0.5, 'no_speech_prob': 0.02},
]

text = format_transcript(mock_segments, model='tiny')
lines = text.strip().split('\n')

assert len(lines) >= 2, f"期望至少 2 行，实际 {len(lines)}"

for i, line in enumerate(lines):
    # 行格式: [说话人 A] [tiny] [0.xx] HH:MM:SS,mmm - HH:MM:SS,mmm
    pattern = r'^\[说话人 A\] \[tiny\] \[\d\.\d{2}\] \d{2}:\d{2}:\d{2},\d{3} - \d{2}:\d{2}:\d{2},\d{3}$'
    assert re.match(pattern, line), f"第 {i} 行格式不正确: {line}"

print("✅ 转录文稿格式验证通过")
```

**运行方式**：
```bash
pi -p "python3 script/verify/04_transcript_format.py"
```

---

### 📝 Commit: `feat(runner): 输出新格式 转录文稿.txt + 视频信息.txt`

**改动文件**：`src/core/runner.py`

---

#### 🔧 开发

**做什么**：
- 写入 `转录文稿.txt`：使用 `format_transcript()` 新格式
- 写入 `视频信息.txt`：替换原来的 `视频链接.txt`

**视频信息.txt 内容**：

```
视频链接: https://www.bilibili.com/video/BV1Gm421W75K/
BV号: BV1Gm421W75K
AV号: AV114514
标题: 赘X的白金作者直播课，全是干货，不容错过
UP主: 瞎写菌
UP主UID: 12345678
发布时间: 2026-07-15 18:30:00
时长: 3539秒 (0:58:59)
分区: 知识
标签: 网文,写作,教程
简介: 白金作者分享写作经验，全是干货……

播放: 12.3万
弹幕: 456
评论: 89
点赞: 2345
硬币: 678
收藏: 1234
转发: 56
```

- 字段来源：

| 字段 | API 来源 |
|------|----------|
| BV号 | `bvid` |
| AV号 | `aid` |
| 标题 | `title` |
| UP主 | `owner.name` |
| UP主UID | `owner.mid` |
| 发布时间 | `pubdate`（时间戳转日期） |
| 时长 | `duration` |
| 分区 | `tname` |
| 简介 | `desc` |
| 播放/弹幕/评论等 | `stat.view` / `stat.danmaku` / ... |

- 不再写入 `字幕.srt`

**不做什么**：
- 不修改已有 `out/` 目录的旧文件（迁移阶段再做）
- 不修改队列调度逻辑

---

#### ✅ 验收

**验收脚本**：`script/verify/05_runner_output.py`

```python
#!/usr/bin/env python3
"""验证 runner 输出新格式文件"""
import sys, os
sys.path.insert(0, '.')
from src.core.runner import run_transcription

# 转录一个短视频
result = run_transcription('BV1EZ4y1d7xC', 'tiny')
assert result['success'], f"转录失败: {result.get('error')}"

video_dir = os.path.dirname(result['srt'].replace('转录文稿.srt', ''))
# 实际新 runner 不再写 srt，检查新文件
out_dir = os.path.join('out', os.listdir('out')[0])

# 检查文件存在
assert os.path.exists(os.path.join(out_dir, '视频信息.txt')), "缺少 视频信息.txt"
assert os.path.exists(os.path.join(out_dir, 'audio.m4s')), "缺少 audio.m4s"
assert os.path.exists(os.path.join(out_dir, '转录文稿.txt')), "缺少 转录文稿.txt"
assert not os.path.exists(os.path.join(out_dir, '字幕.srt')), "不应存在 字幕.srt"

# 检查转录文稿格式
with open(os.path.join(out_dir, '转录文稿.txt')) as f:
    first_line = f.readline().strip()
assert first_line.startswith('[说话人 A]'), f"格式错误: {first_line}"

print("✅ runner 输出格式验证通过")
```

**运行方式**：
```bash
pi -p "python3 script/verify/05_runner_output.py"
```

---

### 📝 Commit: `feat(cli): 新增 transcript-to-srt 子命令`

**改动文件**：`src/cli/main.py`

---

#### 🔧 开发

**做什么**：
- 新增子命令 `bili-scribe transcript-to-srt <输入路径> [输出路径]`
- 从 `转录文稿.txt` 行首时间戳提取 start/end
- 生成标准 SRT 格式：

```
1
00:00:01,230 --> 00:00:52,100
大家好，今天我们来聊聊网文写作。首先……

2
00:00:52,100 --> 00:03:04,700
我觉得最重要的是人物塑造，一个好的角色……
```

- 未指定输出路径时，默认与输入同目录，后缀 `.srt`

**不做什么**：
- 不修改 `转录文稿.txt`
- 不批量处理（只处理单个文件）

---

#### ✅ 验收

**验收脚本**：`script/verify/06_transcript_to_srt.py`

```python
#!/usr/bin/env python3
"""验证 transcript-to-srt 子命令"""
import sys, os, subprocess, re
sys.path.insert(0, '.')

# 创建一个测试用的转录文稿.txt
test_dir = '/tmp/test_srt'
os.makedirs(test_dir, exist_ok=True)
test_input = os.path.join(test_dir, '转录文稿.txt')
test_output = os.path.join(test_dir, '转录文稿.srt')

with open(test_input, 'w') as f:
    f.write('[说话人 A] [tiny] [0.82] 00:00:01,230 - 00:00:05,100\n')
    f.write('大家好，今天我们来聊聊\n')
    f.write('\n')
    f.write('[说话人 B] [tiny] [0.95] 00:00:05,100 - 00:00:10,500\n')
    f.write('我觉得最重要的是人物塑造\n')

# 运行命令
result = subprocess.run(
    [sys.executable, '-m', 'src.cli.main', 'transcript-to-srt', test_input],
    capture_output=True, text=True
)
assert result.returncode == 0, f"命令失败: {result.stderr}"
assert os.path.exists(test_output), "输出文件未生成"

# 验证 SRT 格式
with open(test_output) as f:
    content = f.read()

assert '00:00:01,230 --> 00:00:05,100' in content, "时间戳格式错误"
assert '大家好，今天我们来聊聊' in content, "文本内容错误"

print("✅ transcript-to-srt 验证通过")
```

**运行方式**：
```bash
pi -p "python3 script/verify/06_transcript_to_srt.py"
```

---

## 阶段三：迁移旧数据

### 📝 Commit: `feat(script): 迁移脚本`

**新增文件**：`script/migrate_to_new_format.py`

---

#### 🔧 开发

**做什么**：
- 扫描 `out/` 下所有目录
- 删除旧格式文件：`书面文稿.txt`、`字幕.srt`、`适配分析.md`
- 改名：`视频链接.txt` → `视频信息.txt`（保留已有内容）
- 提取所有 BV ID
- 批量调用 `bili-scribe queue add` 加入队列（模型 `tiny`）
- 写入 `~/.queue/operations.log`：

```
2026-08-07T15:00:00 [MIGRATE] 删除: 书面文稿.txt x118, 字幕.srt x75, 适配分析.md x17
2026-08-07T15:00:05 [MIGRATE] 改名: 视频链接.txt → 视频信息.txt x131
2026-08-07T15:01:00 [QUEUE] 批量添加 131 个任务到队列 (模型: tiny)
```

- 支持 `--dry-run` 参数预览操作

**不做什么**：
- 不删除 `audio.m4s`
- 不重新转录（只清理和入队）
- 不修改旧 `转录文稿.txt`（新转录会覆盖）

---

#### ✅ 验收

**验收脚本**：`script/verify/07_migrate_dry_run.py`

```python
#!/usr/bin/env python3
"""验证迁移脚本 dry-run 模式"""
import sys, subprocess
sys.path.insert(0, '.')

result = subprocess.run(
    [sys.executable, 'script/migrate_to_new_format.py', '--dry-run'],
    capture_output=True, text=True
)
assert result.returncode == 0, f"迁移脚本失败: {result.stderr}"
output = result.stdout
assert '删除' in output, "输出应包含删除信息"
assert '改名' in output, "输出应包含改名信息"
assert '添加' in output, "输出应包含添加信息"
print("✅ 迁移脚本 dry-run 验证通过")
```

**运行方式**：
```bash
pi -p "python3 script/verify/07_migrate_dry_run.py"
```

---

### 📝 执行迁移

**运行方式**（由用户确认后手动执行）：
```bash
python3 script/migrate_to_new_format.py
```

#### ✅ 验收

**验收脚本**：`script/verify/08_migrate_result.py`

```python
#!/usr/bin/env python3
"""验证迁移结果"""
import sys, os, subprocess
sys.path.insert(0, '.')

out_dir = 'out'

# 1. 旧文件已清理
old_files = ['书面文稿.txt', '字幕.srt', '适配分析.md']
for name in old_files:
    count = int(subprocess.run(
        ['find', out_dir, '-name', name, '-type', 'f'],
        capture_output=True, text=True
    ).stdout.strip().count('\n') or 0)
    assert count == 0, f"仍有 {count} 个 {name} 未被清理"

# 2. 已改名
count = int(subprocess.run(
    ['find', out_dir, '-name', '视频信息.txt', '-type', 'f'],
    capture_output=True, text=True
).stdout.strip().count('\n') or 0)
print(f"✅ 视频信息.txt: {count} 个")

# 3. 队列新增
result = subprocess.run(
    [sys.executable, '-m', 'src.cli.main', 'queue', 'status'],
    capture_output=True, text=True
)
assert '待处理' in result.stdout, "队列状态异常"

# 4. operations.log
log_path = os.path.expanduser('~/.queue/operations.log')
assert os.path.exists(log_path), "缺少 operations.log"

print("✅ 迁移验证通过")
```

**运行方式**：
```bash
pi -p "python3 script/verify/08_migrate_result.py"
```

---

## 阶段四：启动队列

### 📝 Commit: `chore(queue): 默认模型改为 tiny`

**改动文件**：`src/cli/bili_queue.py`

---

#### 🔧 开发

**做什么**：
- `bili_queue.py` 中默认模型 `small` → `tiny`
- `MODEL_MEMORY_REQUIREMENTS` 中 `tiny` 阈值已为 500MB，无需修改

**不做什么**：
- 不修改已有任务（已入队任务保留原模型）

---

#### ✅ 验收

**验收脚本**：`script/verify/09_queue_ready.py`

```python
#!/usr/bin/env python3
"""验证队列就绪"""
import sys, subprocess
sys.path.insert(0, '.')

result = subprocess.run(
    [sys.executable, '-m', 'src.cli.main', 'queue', 'status'],
    capture_output=True, text=True
)
assert '待处理' in result.stdout, "队列状态异常"
print("✅ 队列就绪")
print(result.stdout)
```

**运行方式**：
```bash
pi -p "python3 script/verify/09_queue_ready.py"
```

---

### 📝 等待 cron 自动调度

**做什么**：
- cron 每 10 分钟自动检查、取任务、转录
- 每个任务完成后检查：
  - 内存稳定在 ~500MB
  - `转录文稿.txt` 格式符合新规范
  - `cron.jsonl` 有完整事件记录

**不做什么**：
- 不做说话人区分（后续独立阶段）

**验收**（1 小时后手动检查）：
```bash
bili-scribe queue list done | wc -l              # 期望: > 0
head -5 out/BVxxx_标题/转录文稿.txt                # 期望: 新格式
tail -10 ~/.queue/cron.jsonl                      # 期望: 连续 task_end
free -m | grep Available                          # 期望: 稳定 ~1200MB
```