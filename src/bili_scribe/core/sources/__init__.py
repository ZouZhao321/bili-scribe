"""媒体源抽象层 — 统一的源协议与实现。

将「获取媒体」（B站 API 交互 / 本地文件）与「转录」（Whisper）解耦：
pipeline 只依赖 MediaSource 协议，不关心源的具体实现。

| 源 | 说明 |
| ------ | ------ |
| BilibiliSource | B 站 URL/BV 号 → 字幕、音频、元数据 |
| LocalFileSource | 本地视频/音频文件 → 直接转录 |
"""

from bili_scribe.core.sources.bilibili import BilibiliSource
from bili_scribe.core.sources.local import LocalFileSource

__all__ = ["BilibiliSource", "LocalFileSource"]
