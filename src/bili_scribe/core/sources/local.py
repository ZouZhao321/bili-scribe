"""本地文件媒体源 — 本地视频/音频文件直接转录.

无需任何 B 站交互；元数据默认取文件名 + ffprobe 时长，
允许调用方通过 title/author 覆盖。本地文件无内置字幕，
转录恒走 Whisper 路径。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


class LocalFileSource:
    """本地媒体文件源 — 文件路径 → 直接转录.

    属性:
        path: 本地媒体文件路径。
    """

    def __init__(self, path: str | Path, title: str = "", author: str = "") -> None:
        """初始化本地源.

        参数:
            path: 本地视频/音频文件路径。
            title: 可选标题覆盖（默认取文件名去扩展名）。
            author: 可选作者覆盖（默认空）。

        抛出:
            FileNotFoundError: 文件不存在或不是普通文件。
        """
        self.path = Path(path).expanduser()
        if not self.path.is_file():
            raise FileNotFoundError(f"文件不存在: {self.path}")
        self._title_override = title
        self._author_override = author
        self._duration: int | None = None

    # ------------------------------------------------------------------
    # MediaSource 协议实现
    # ------------------------------------------------------------------

    @property
    def source_id(self) -> str:
        """源标识 — 文件名去扩展名."""
        return self.path.stem

    def get_metadata(self) -> dict:
        """获取元数据：标题（覆盖或文件名）、作者、时长（ffprobe）.

        返回:
            {"title": str, "author": str, "duration": int(秒),
             "raw": {}, "dir_name": str(输出目录名)}
        """
        title = self._title_override or self.path.stem
        # 目录名：默认标题（与源标识相同）时单段，覆盖标题时双段拼接
        # 覆盖标题需清理 Windows 保留字符（: * ? " < > | 等），否则 mkdir 抛 OSError
        safe_title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title[:100]).replace(" ", "_")
        dir_name = f"{self.path.stem}_{safe_title}" if self._title_override else self.path.stem
        return {
            "title": title,
            "author": self._author_override,
            "duration": self._probe_duration(),
            "raw": {},
            "dir_name": dir_name,
        }

    def get_subtitles(self) -> list[dict]:
        """本地文件无内置字幕，恒返回空列表.

        返回:
            空列表（pipeline 将降级走 Whisper）。
        """
        return []

    def get_audio(self, out_path: Path) -> Path | None:
        """本地文件直接可转录（faster-whisper 经 PyAV 解码），返回原路径.

        参数:
            out_path: 兼容协议签名，本地源不使用（文件已存在）。

        返回:
            原媒体文件路径（已校验存在）。
        """
        return self.path

    def meta_lines(self) -> list[str]:
        """生成简化版「视频信息.txt」文本行.

        返回:
            {"来源", "文件路径", "标题", "作者", "时长"} 文本行列表。
        """
        meta = self.get_metadata()
        dur = meta["duration"]
        dur_str = f"{dur}秒"
        if dur > 0:
            h, m = divmod(dur, 3600)
            m, s = divmod(m, 60)
            if h > 0:
                dur_str += f" ({h}:{m:02d}:{s:02d})"
            else:
                dur_str += f" ({m}:{s:02d})"
        return [
            "来源: 本地文件",
            f"文件路径: {self.path}",
            f"标题: {meta['title']}",
            f"作者: {meta['author'] or '未知'}",
            f"时长: {dur_str}",
        ]

    def get_error(self) -> str:
        """本地源无特殊获取错误，恒返回空字符串."""
        return ""

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _probe_duration(self) -> int:
        """用 ffprobe 读取媒体时长（秒），失败返回 0（结果缓存）.

        返回:
            媒体时长（秒），无法读取时返回 0。
        """
        if self._duration is not None:
            return self._duration
        try:
            out = subprocess.run(  # noqa: S603  # 参数来自本地文件路径
                [  # noqa: S607  # 固定可执行名，经 PATH 解析
                    "ffprobe",
                    "-v",
                    "quiet",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "csv=p=0",
                    str(self.path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if out.returncode == 0 and out.stdout.strip():
                self._duration = int(float(out.stdout.strip()))
            else:
                self._duration = 0
        except (subprocess.SubprocessError, ValueError, OSError):
            self._duration = 0
        return self._duration
