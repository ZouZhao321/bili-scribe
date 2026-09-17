"""Bilibili 媒体源 — 从 B 站获取字幕、音频与元数据.

将原 runner.py 中的 B 站获取逻辑下沉到本模块，
统一实现 MediaSource 协议，供 pipeline 无差别转录。
"""

from __future__ import annotations

import subprocess
import sys
import urllib.error
from datetime import datetime
from pathlib import Path

from bili_scribe.core.bilibili import (
    download_audio,
    download_subtitle_json,
    extract_bvid,
    get_audio_url,
    get_cid,
    get_subtitle_url,
    get_video_info,
    get_video_url,
)


def _best_effort_unlink(path: Path) -> None:
    """尽力删除文件，失败仅打日志不抛异常（Windows 文件锁场景）."""
    try:
        path.unlink()
    except OSError as e:
        print(f"[bilibili] 删除临时文件失败: {e}", file=sys.stderr)


class BilibiliSource:
    """B 站视频源 — URL/BV 号 → 字幕、音频与元数据.

    属性:
        bvid: 解析出的视频 BV 号。
        page: 分 P 序号（0-indexed）。
        cookie: B 站登录 Cookie。
    """

    def __init__(self, url: str, page: int = 0, cookie: str = "") -> None:
        """初始化 B 站源.

        参数:
            url: B 站视频链接或 BV ID。
            page: 分 P 序号（0-indexed）。
            cookie: B 站登录 Cookie。

        抛出:
            SystemExit: URL 无法解析出有效 BV ID 时。
        """
        self.bvid = extract_bvid(url)
        self.page = page
        self.cookie = cookie
        self._info: dict = {}
        self._cid: str | None = None
        self._cid_error: str = ""

    # ------------------------------------------------------------------
    # MediaSource 协议实现
    # ------------------------------------------------------------------

    @property
    def source_id(self) -> str:
        """源标识 — B 站视频为 BV 号."""
        return self.bvid

    def get_metadata(self) -> dict:
        """获取视频元数据，信息获取失败降级为默认值.

        返回:
            {"title": str, "author": str, "duration": int,
             "raw": B站原始 video_info 字典}
        """
        try:
            self._info = get_video_info(self.bvid)
        except (Exception, SystemExit) as e:  # noqa: BLE001  # 信息获取失败降级为默认值，与 runner 原行为一致
            print(f"[bilibili] 获取视频信息失败，降级使用默认标题: {e}", file=sys.stderr)
            self._info = {}
        return {
            "title": self._info.get("title", self.bvid),
            "author": self._info.get("owner", {}).get("name", ""),
            "duration": self._info.get("duration", 0),
            "raw": self._info,
        }

    def get_subtitles(self) -> list[dict]:
        """获取 CC/AI 字幕（CC 优先于 AI），无可用字幕返回空列表.

        返回:
            字幕片段字典列表（每段含 from/to/content），
            无字幕或获取失败时返回空列表（由 pipeline 降级 Whisper）。
        """
        cid = self._get_cid()
        if cid is None:
            return []
        try:
            sub_list = get_subtitle_url(self.bvid, cid, self.cookie)
            if not sub_list:
                return []
            cc_subs = [s for s in sub_list if not s.get("lan", "").startswith("ai")]
            ai_subs = [s for s in sub_list if s.get("lan", "").startswith("ai")]
            for sub in cc_subs + ai_subs:
                sub_url = sub.get("subtitle_url")
                if not sub_url:
                    continue  # 坏条目跳过，不中断后续有效字幕
                try:
                    sub_data = download_subtitle_json(sub_url)
                    body = sub_data.get("body", [])
                    if body:
                        return body
                except (urllib.error.URLError, ValueError, AttributeError) as e:  # 单个字幕条目失败，继续尝试下一个
                    print(f"[bilibili] 字幕条目下载失败，尝试下一个: {e}", file=sys.stderr)
                    continue
        except (Exception, SystemExit):  # noqa: BLE001, S110  # 字幕获取失败静默降级 Whisper（含 SystemExit）
            pass
        return []

    def get_audio(self, out_path: Path) -> Path | None:
        """下载音频到 out_path（DASH 优先，FLV+ffmpeg 回退）.

        参数:
            out_path: 音频下载目标路径（如 out/BV_标题/audio.m4s）。

        返回:
            成功时返回音频文件路径，失败返回 None。
        """
        cid = self._get_cid()
        if cid is None:
            return None

        # DASH 格式：直接下载音频流
        audio_url = get_audio_url(self.bvid, cid)
        if audio_url:
            referer = f"https://www.bilibili.com/video/{self.bvid}/"
            if download_audio(audio_url, str(out_path), referer):
                return out_path
            return None

        # DASH 不可用，回退到 FLV 格式 → ffmpeg 提取音频
        video_url = get_video_url(self.bvid, cid)
        if not video_url:
            return None
        video_path = out_path.with_name("video.flv")  # 与原 runner 临时文件名保持一致
        referer = f"https://www.bilibili.com/video/{self.bvid}/"
        if not download_audio(video_url, str(video_path), referer):
            return None
        if not video_path.exists():
            return None
        try:
            subprocess.run(  # noqa: S603  # 参数来自本地文件路径/可信解析结果
                [  # noqa: S607  # 固定可执行名，经 PATH 解析
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(video_path),
                    "-vn",
                    "-acodec",
                    "copy",
                    "-f",
                    "mp4",
                    str(out_path),
                ],
                check=True,
                capture_output=True,
            )
        except (subprocess.CalledProcessError, OSError) as e:
            # ffmpeg 缺失或提取失败：符合协议约定返回 None，不向上抛；残留临时文件一并清理
            print(f"[bilibili] ffmpeg 提取音频失败: {e}", file=sys.stderr)
            _best_effort_unlink(video_path)
            return None
        _best_effort_unlink(video_path)  # 删除视频文件，保留音频（清理失败不影响已成功的提取）
        return out_path

    def meta_lines(self) -> list[str]:
        """生成「视频信息.txt」文本行（纯视频元数据，不含转录信息）.

        即使元数据获取失败也返回完整行（默认值兜底），
        与原 runner 无条件写入「视频信息.txt」的行为一致。

        返回:
            与原 runner 输出逐行一致的文本行列表（恒非空）。
        """
        info = self._info
        bvid = self.bvid
        title = info.get("title", bvid)
        duration = info.get("duration", 0)
        owner = info.get("owner", {})
        stat = info.get("stat", {})

        # 时长格式化
        h, m = divmod(duration, 3600)
        m, s = divmod(m, 60)
        dur_str = f"{duration}秒"
        if h > 0:
            dur_str += f" ({h}:{m:02d}:{s:02d})"
        else:
            dur_str += f" ({m}:{s:02d})"

        # 发布时间
        pubdate = info.get("pubdate", 0)
        pubdate_str = datetime.fromtimestamp(pubdate).strftime("%Y-%m-%d %H:%M:%S") if pubdate else "未知"

        # 播放量格式化
        def fmt_num(n: int) -> str:
            if n >= 10000:
                return f"{n / 10000:.1f}万"
            return str(n)

        return [
            f"视频链接: https://www.bilibili.com/video/{bvid}/",
            f"BV号: {bvid}",
            f"AV号: AV{info.get('aid', '')}",
            f"标题: {title}",
            f"UP主: {owner.get('name', '未知')}",
            f"UP主UID: {owner.get('mid', '')}",
            f"发布时间: {pubdate_str}",
            f"时长: {dur_str}",
            f"分区: {info.get('tname', '')}",
            f"标签: {info.get('videos', '')}",
            f"简介: {info.get('desc', '')}",
            "",
            f"播放: {fmt_num(stat.get('view', 0))}",
            f"弹幕: {fmt_num(stat.get('danmaku', 0))}",
            f"评论: {fmt_num(stat.get('reply', 0))}",
            f"点赞: {fmt_num(stat.get('like', 0))}",
            f"硬币: {fmt_num(stat.get('coin', 0))}",
            f"收藏: {fmt_num(stat.get('favorite', 0))}",
            f"转发: {fmt_num(stat.get('share', 0))}",
        ]

    def get_error(self) -> str:
        """返回最近一次获取失败的描述，无错误返回空字符串."""
        return self._cid_error

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _get_cid(self) -> str | None:
        """获取当前分 P 的 CID，失败时记录错误并返回 None（结果缓存）.

        get_subtitles() 与 get_audio() 都可能调用，缓存避免重复请求
        pagelist API（与旧 runner 单次调用一致）。实例的 page 固定，
        缓存安全；失败结果同样缓存，避免重复请求与 stale state。

        返回:
            成功时返回 CID 字符串，失败返回 None。
        """
        if self._cid is not None:
            return self._cid
        if self._cid_error:  # 失败结果同样缓存（含超时后的重试场景），避免重复请求
            return None
        try:
            cid, _part_title, _total = get_cid(self.bvid, self.page)
            self._cid = str(cid)
            return self._cid
        except (Exception, SystemExit) as e:  # noqa: BLE001  # 与 runner 原行为一致：CID 获取失败转为任务失败返回
            self._cid_error = f"获取 CID 失败: {e}"
            return None
