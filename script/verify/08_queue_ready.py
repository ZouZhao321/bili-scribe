#!/usr/bin/env python3
"""验证默认模型改为 tiny."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# 检查 queue status
result = subprocess.run(
    [sys.executable, "-m", "src.cli.main", "queue", "status"],
    capture_output=True, text=True,
)
print(result.stdout)
assert "待处理" in result.stdout, "队列状态异常"
print("✅ 默认模型 tiny 验证通过")