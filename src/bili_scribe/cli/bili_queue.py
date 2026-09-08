#!/usr/bin/env python3
"""Bilibili 转录任务队列 — CLI 入口（已废弃，请使用 HTTP API）.

队列操作已迁移到 Web 服务：
  - 提交任务:    POST /api/v1/transcribe
  - 查看状态:    GET  /api/v1/health
  - 列出任务:    GET  /api/v1/tasks
  - 查询任务:    GET  /api/v1/transcribe/{task_id}
  - 重试任务:    POST /api/v1/tasks/{task_id}/retry
  - 删除任务:    DELETE /api/v1/tasks/{task_id}
  - 取消任务:    POST /api/v1/tasks/{task_id}/cancel

启动 Web 服务: bili-scribe serve
"""

import argparse
import sys

_DEPRECATION_MSG = """
╔══════════════════════════════════════════════════════════════╗
║  ⚠️  此 CLI 命令已废弃，请使用 HTTP API 或 Web 界面操作。    ║
║                                                              ║
║  替代方案:                                                    ║
║    提交任务:  POST /api/v1/transcribe                         ║
║    查看状态:  GET  /api/v1/health                             ║
║    列出任务:  GET  /api/v1/tasks                              ║
║    查询任务:  GET  /api/v1/transcribe/{task_id}              ║
║                                                              ║
║  启动服务:    bili-scribe serve                               ║
║  API 文档:    http://localhost:8000/docs                      ║
╚══════════════════════════════════════════════════════════════╝
"""


# ---------------------------------------------------------------------------
# 废弃命令（输出迁移提示）
# ---------------------------------------------------------------------------
def _deprecated(_args):
    """输出废弃提示并退出."""
    print(_DEPRECATION_MSG)
    sys.exit(1)


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Bilibili 转录任务队列管理（已废弃）")
    sub = parser.add_subparsers(dest="command", help="可用命令")

    # 所有命令都指向废弃提示
    for cmd_name in ["add", "status", "list", "retry", "remove", "cancel", "clear"]:
        sub.add_parser(cmd_name, help=f"（已废弃）{cmd_name}")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    _deprecated(args)


if __name__ == "__main__":
    main()
