"""Tests for the commit message checker (script/check_commit_msg.py)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "script" / "check_commit_msg.py"


def run_checker(tmp_path: Path, title: str) -> int:
    """Run the checker against a title and return its exit code."""
    message_file = tmp_path / "COMMIT_EDITMSG"
    message_file.write_text(f"{title}\n", encoding="utf-8")
    command = [sys.executable, str(SCRIPT), str(message_file)]
    # The checker is a local script and every argument comes from this test.
    result = subprocess.run(command, capture_output=True)  # noqa: S603
    return result.returncode


class TestCommitMessageChecker:
    """Gate installed as the commit-msg hook."""

    def test_accepts_conventional_title(self, tmp_path: Path) -> None:
        assert run_checker(tmp_path, "fix(queue): 修复任务重复入队") == 0

    def test_accepts_skipped_prefixes(self, tmp_path: Path) -> None:
        assert run_checker(tmp_path, "Merge branch 'main' into feat/quota") == 0
        assert run_checker(tmp_path, "fixup! fix(queue): 修复任务重复入队") == 0

    def test_rejects_title_without_allowed_type(self, tmp_path: Path) -> None:
        assert run_checker(tmp_path, "update: 修改了一些文件") == 1

    def test_rejects_review_round_reference(self, tmp_path: Path) -> None:
        assert run_checker(tmp_path, "fix(core): 修复 ocr 第二轮审核 9 项 — 异常逃逸与互斥校验") == 1
        assert run_checker(tmp_path, "fix(core): 第三轮审核修正下载失败清理") == 1

    def test_rejects_reviewer_reference(self, tmp_path: Path) -> None:
        assert run_checker(tmp_path, "fix(core): 按 ocr 审核修复下载失败清理") == 1

    def test_rejects_batch_item_count(self, tmp_path: Path) -> None:
        assert run_checker(tmp_path, "fix(core): 修复 9 项") == 1
        assert run_checker(tmp_path, "fix(core): 修复下载失败 13 项发现") == 1

    def test_accepts_titles_that_only_mention_counts_or_tool_names(self, tmp_path: Path) -> None:
        assert run_checker(tmp_path, "feat(api): 新增 3 项过滤参数") == 0
        assert run_checker(tmp_path, "feat(ocr): 新增图片字幕识别") == 0
