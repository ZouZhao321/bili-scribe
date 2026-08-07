#!/usr/bin/env python3
"""验证 format_transcript 输出格式正确."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from src.core.transcriber import format_transcript

# 模拟 Whisper 返回数据
mock_segments = [
    {"from": 1.23, "to": 5.10, "content": "大家好", "avg_logprob": -0.2, "no_speech_prob": 0.01},
    {"from": 5.10, "to": 10.50, "content": "今天我们来聊聊", "avg_logprob": -0.5, "no_speech_prob": 0.02},
    {"from": 10.50, "to": 15.00, "content": "", "avg_logprob": -0.1, "no_speech_prob": 0.5},  # 空内容应跳过
]

text = format_transcript(mock_segments, model="tiny")
lines = [l for l in text.strip().split("\n") if l.strip()]

# 空内容段应被跳过，所以只有 2 段（4 行：2 段 × 2 行/段）
assert len(lines) == 4, f"期望 4 行，实际 {len(lines)}: {lines}"

# 行格式: [说话人 A] [tiny] [0.xx] HH:MM:SS,mmm - HH:MM:SS,mmm
pattern = r"^\[说话人 A\] \[tiny\] \[\d+\.\d{2}\] \d{2}:\d{2}:\d{2},\d{3} - \d{2}:\d{2}:\d{2},\d{3}$"
for i, line in enumerate(lines):
    if i % 2 == 0:  # 元数据行
        assert re.match(pattern, line), f"第 {i} 行格式不正确: {line}"
    else:  # 内容行
        assert not line.startswith("["), f"第 {i} 行不应是元数据: {line}"

print("✅ 转录文稿格式验证通过")
print(text)