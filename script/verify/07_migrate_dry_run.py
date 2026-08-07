#!/usr/bin/env python3
"""验证迁移脚本 dry-run 模式."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

result = subprocess.run(
    [sys.executable, "script/migrate_to_new_format.py", "--dry-run"],
    capture_output=True, text=True,
)
assert result.returncode == 0, f"迁移脚本失败: {result.stderr}"
output = result.stdout
assert "删除" in output, "输出应包含删除信息"
assert "改名" in output, "输出应包含改名信息"
assert "加入队列" in output, "输出应包含加入队列信息"
print("✅ 迁移脚本 dry-run 验证通过")
print(output[:500])