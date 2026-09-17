"""媒体源协议 — 所有源统一实现的接口约定。

pipeline 通过本协议无差别消费任何媒体源（B站视频、本地文件），
新增源类型只需实现协议，无需改动转录编排。
"""

from pathlib import Path
from typing import Protocol


class MediaSource(Protocol):
    """媒体源协议 — 提供转录所需的全部输入.

    实现约定:
        source_id: 源唯一标识（B站为 BV 号，本地为文件名去扩展名）。
        get_metadata: 返回元数据字典，键为 title/author/duration/raw。
        get_subtitles: 返回内置字幕片段列表，无字幕返回空列表。
        get_audio: 确保存在可转录的音频文件，返回其路径或 None。
        meta_lines: 生成「视频信息.txt」的文本行，无需元数据文件时返回空列表。
        get_error: 返回最近一次获取失败的描述，无错误返回空字符串（可选）。
    """

    @property
    def source_id(self) -> str:
        """源唯一标识."""
        ...

    def get_metadata(self) -> dict:
        """获取元数据.

        返回:
            {"title": str, "author": str, "duration": int(秒),
             "raw": dict(源原始元数据),
             "dir_name": str(可选，输出目录名覆盖；缺省时 pipeline
             拼接 {source_id}_{安全标题})}
        """
        ...

    def get_subtitles(self) -> list[dict]:
        """获取内置字幕片段列表.

        返回:
            字幕片段字典列表（每段含 from/to/content），无字幕返回空列表.
        """
        ...

    def get_audio(self, out_path: Path) -> Path | None:
        """确保存在可转录的音频文件.

        参数:
            out_path: 需要时下载/提取音频的目标路径（本地源可能直接返回原文件）.

        返回:
            可转录的音频文件路径，失败返回 None.
        """
        ...

    def meta_lines(self) -> list[str]:
        """生成「视频信息.txt」的文本行.

        返回:
            写入元数据文件的文本行列表，无需元数据文件时返回空列表.
        """
        ...

    def get_error(self) -> str:
        """返回最近一次获取失败的描述，无错误返回空字符串（可选实现）.

        返回:
            获取失败原因描述（如 "获取 CID 失败: ..."），无错误返回 "".
        """
        ...
