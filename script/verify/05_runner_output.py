#!/usr/bin/env python3
"""验证 runner 输出新格式文件."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from src.core.runner import run_transcription

# 转录一个短视频（有 CC/AI 字幕的）
result = run_transcription("BV1EZ4y1d7xC", "tiny")
assert result["success"], f"转录失败: {result.get('error')}"

# 找到输出目录
transcript_path = Path(result["transcript"])
video_dir = transcript_path.parent

# 检查文件存在
assert (video_dir / "视频信息.txt").exists(), "缺少 视频信息.txt"
assert (video_dir / "转录文稿.txt").exists(), "缺少 转录文稿.txt"
assert not (video_dir / "字幕.srt").exists(), "不应存在 字幕.srt"

# 检查视频信息内容
with open(video_dir / "视频信息.txt") as f:
    info_content = f.read()
assert "BV号:" in info_content, "视频信息.txt 缺少 BV号"
assert "UP主:" in info_content, "视频信息.txt 缺少 UP主"
# 不应包含转录模型/时间
assert "转录模型:" not in info_content, "视频信息.txt 不应包含转录模型"
assert "转录时间:" not in info_content, "视频信息.txt 不应包含转录时间"

# 检查转录文稿格式
with open(video_dir / "转录文稿.txt") as f:
    first_line = f.readline().strip()
assert first_line.startswith("[说话人 A]"), f"格式错误: {first_line}"

print(f"✅ runner 输出格式验证通过")
print(f"  目录: {video_dir}")
print(f"  文件: {[p.name for p in video_dir.iterdir()]}")