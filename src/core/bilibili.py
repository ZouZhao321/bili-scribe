"""Bilibili API 交互层 — 视频信息获取、字幕下载、音频流获取。

提供与 B 站 API 通信的所有函数，不涉及 Whisper 转录逻辑。
"""

import json
import re
import sys
import urllib.error
import urllib.request

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com",
}


def api_get(url: str, cookie: str = "") -> dict:
    """发送 GET 请求到 B 站 API。

    参数：
        url: API 端点 URL。
        cookie: 可选的 B 站 Cookie，用于需要登录的请求。

    返回：
        解析后的 JSON 响应字典。

    抛出：
        SystemExit: 如果请求失败或返回 HTTP 错误。
    """
    headers = dict(HEADERS)
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"HTTP 错误 {e.code}: {e.reason}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"请求错误: {e}", file=sys.stderr)
        sys.exit(1)


def extract_bvid(url: str) -> str:
    """从各种 B 站链接格式中提取 BV ID。

    支持标准链接、短链接 (b23.tv) 和旧的 av 号格式。
    纯 BV ID 字符串会原样返回。

    参数：
        url: B 站视频链接、短链接或 BV/av ID。

    返回：
        12 位 BV ID 字符串。

    抛出：
        SystemExit: 如果无法从 URL 解析出有效的 BV ID。
    """
    if "b23.tv" in url:
        req = urllib.request.Request(url, headers=HEADERS)
        req.method = "HEAD"
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                url = resp.url
        except urllib.error.URLError:
            pass

    m = re.search(r"(BV[\w]{10})", url)
    if m:
        return m.group(1)

    m = re.search(r"av(\d+)", url)
    if m:
        aid = m.group(1)
        data = api_get(f"https://api.bilibili.com/x/web-interface/view?aid={aid}")
        if data.get("code") == 0:
            return data["data"]["bvid"]
        print(f"错误: 无法解析 av{aid}", file=sys.stderr)
        sys.exit(1)

    print(f"错误: 无法从 URL 提取 BV ID: {url}", file=sys.stderr)
    sys.exit(1)


def get_cid(bvid: str, page: int = 0) -> tuple:
    """获取视频的 CID 和分页信息。

    参数：
        bvid: 视频的 12 位 BV ID。
        page: 分 P 序号（从 0 开始）。

    返回：
        (cid, part_title, total_pages) 元组。

    抛出：
        SystemExit: 如果视频分页 API 请求失败。
    """
    data = api_get(f"https://api.bilibili.com/x/player/pagelist?bvid={bvid}")
    if data.get("code") != 0 or not data.get("data"):
        print(f"错误: 无法获取 {bvid} 的分页列表", file=sys.stderr)
        sys.exit(1)

    pages = data["data"]
    if page >= len(pages):
        page = 0

    cid = pages[page]["cid"]
    part_title = pages[page].get("part", "")
    return cid, part_title, len(pages)


def get_video_info(bvid: str) -> dict:
    """从 B 站 API 获取视频元数据。

    参数：
        bvid: 视频的 12 位 BV ID。

    返回：
        包含标题、时长、UP 主等信息的视频元数据字典，失败时返回空字典。
    """
    data = api_get(f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}")
    if data.get("code") != 0:
        return {}
    return data.get("data", {})


def get_subtitle_url(bvid: str, cid: str, cookie: str = "") -> list:
    """从播放器 API 获取可用的字幕 URL 列表。

    参数：
        bvid: 视频的 12 位 BV ID。
        cid: 视频分 P 的 CID。
        cookie: 可选的 B 站 Cookie，用于需要登录的请求。

    返回：
        字幕元数据字典列表，每个字典包含 subtitle_url 字段。
        如果没有可用字幕则返回空列表。
    """
    url = f"https://api.bilibili.com/x/player/v2?bvid={bvid}&cid={cid}"
    data = api_get(url, cookie)
    if data.get("code") != 0:
        return []
    return data.get("data", {}).get("subtitle", {}).get("subtitles", [])


def download_subtitle_json(subtitle_url: str) -> dict:
    """下载并解析字幕 JSON 文件。

    参数：
        subtitle_url: 字幕 JSON 资源的 URL，可能以 '//' 开头（协议相对）。

    返回：
        解析后的字幕 JSON 字典，包含 'body' 键对应字幕片段列表。

    抛出：
        urllib.error.URLError: 如果下载失败。
    """
    if subtitle_url.startswith("//"):
        subtitle_url = "https:" + subtitle_url
    req = urllib.request.Request(subtitle_url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_audio_url(bvid: str, cid: str) -> str | None:
    """从 B 站 playurl API 获取音频流 URL。

    参数：
        bvid: 视频的 12 位 BV ID。
        cid: 视频分 P 的 CID。

    返回：
        音频流基础 URL，如果不可用则返回 None。
    """
    url = f"https://api.bilibili.com/x/player/playurl?bvid={bvid}&cid={cid}&fnval=16&qn=64"
    data = api_get(url)
    if data.get("code") != 0:
        return None
    dash = data.get("data", {}).get("dash", {})
    audio_list = dash.get("audio", [])
    if audio_list:
        return audio_list[0].get("baseUrl")
    return None


def download_audio(audio_url: str, output_path: str, referer: str = "") -> bool:
    """使用分块读取将音频流下载到本地文件。

    参数：
        audio_url: 音频流 URL。
        output_path: 保存音频的本地文件路径。
        referer: 可选的 HTTP Referer 头值。

    返回：
        下载成功返回 True，失败返回 False。
    """
    headers = dict(HEADERS)
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(audio_url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            total = 0
            with open(output_path, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    total += len(chunk)
            print(f"已下载 {total} 字节", file=sys.stderr)
            return True
    except (urllib.error.URLError, OSError) as e:
        print(f"下载错误: {e}", file=sys.stderr)
        return False


def get_collection_info(bvid: str) -> dict | None:
    """获取视频所属合集 (ugc_season) 信息.

    参数:
        bvid: 视频 BV ID

    返回:
        包含 title/cover/ep_count/videos 的字典，非合集视频返回 None.
    """
    info = get_video_info(bvid)
    season = info.get("ugc_season")
    if not season:
        return None

    title = season.get("title", "未命名合集")
    cover = season.get("cover", "")
    ep_count = season.get("ep_count", 0)

    videos = []
    for section in season.get("sections", []):
        for ep in section.get("episodes", []):
            videos.append({
                "bvid": ep.get("bvid", ""),
                "title": ep.get("title", ""),
                "aid": ep.get("aid", 0),
                "cid": ep.get("cid", 0),
            })

    return {
        "title": title,
        "cover": cover,
        "ep_count": ep_count,
        "videos": videos,
    }
