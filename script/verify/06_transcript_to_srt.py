#!/usr/bin/env python3
"""验证 transcript-to-srt 子命令."""
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# 创建一个测试用的转录文稿.txt
test_dir = Path("/tmp/test_srt")
test_dir.mkdir(parents=True, exist_ok=True)
test_input = test_dir / "转录文稿.txt"
test_output = test_dir / "转录文稿.srt"

with open(test_input, "w") as f:
    f.write("[说话人 A] [tiny] [0.82] 00:00:01,230 - 00:00:05,100\n")
    f.write("大家好，今天我们来聊聊\n")
    f.write("\n")
    f.write("[说话人 B] [tiny] [0.95] 00:00:05,100 - 00:00:10,500\n")
    f.write("我觉得最重要的是人物塑造\n")

# 运行命令
result = subprocess.run(
    [sys.executable, "-m", "src.cli.main", "transcript-to-srt", str(test_input)],
    capture_output=True, text=True,
)
assert result.returncode == 0, f"命令失败: {result.stderr}"
assert test_output.exists(), "输出文件未生成"

# 验证 SRT 格式
with open(test_output) as f:
    content = f.read()

assert "00:00:01,230 --> 00:00:05,100" in content, "时间戳格式错误"
assert "大家好，今天我们来聊聊" in content, "文本内容错误"

# 验证 SRT 序号
lines = content.strip().split("\n")
assert lines[0] == "1", f"SRT 序号错误: {lines[0]}"
assert lines[4] == "2", f"SRT 序号错误: {lines[4]}"

print("✅ transcript-to-srt 验证通过")