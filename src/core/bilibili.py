"""Bilibili API 交互层 — 视频信息获取、字幕下载、音频流获取。

提供与 B 站 API 通信的所有函数，不涉及 Whisper 转录逻辑。
"""
import json
import re
import sys
import urllib.error
import urllib.request
from typing import Optional


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com",
}


def api_get(url: str, cookie: str = "") -> dict:
    """Send a GET request to the Bilibili API.

    Args:
        url: The API endpoint URL.
        cookie: Optional Bilibili cookie string for authenticated requests.

    Returns:
        Parsed JSON response as a dictionary.

    Raises:
        SystemExit: If the request fails or returns an HTTP error.
    """
    headers = dict(HEADERS)
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code}: {e.reason}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Request error: {e}", file=sys.stderr)
        sys.exit(1)


def extract_bvid(url: str) -> str:
    """Extract the BV ID from various Bilibili URL formats.

    Supports standard URLs, short links (b23.tv), and old av-number format.
    A bare BV ID string is returned as-is.

    Args:
        url: Bilibili video URL, short link, or BV/av ID.

    Returns:
        The 12-character BV ID string.

    Raises:
        SystemExit: If the URL cannot be parsed into a valid BV ID.
    """
    if "b23.tv" in url:
        req = urllib.request.Request(url, headers=HEADERS)
        req.method = "HEAD"
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                url = resp.url
        except Exception:
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
        print(f"Error: cannot resolve av{aid}", file=sys.stderr)
        sys.exit(1)

    print(f"Error: cannot extract BV ID from URL: {url}", file=sys.stderr)
    sys.exit(1)


def get_cid(bvid: str, page: int = 0) -> tuple:
    """Get the CID and pagination info for a video.

    Args:
        bvid: The 12-character BV ID of the video.
        page: Zero-indexed page number (for multi-part videos).

    Returns:
        A tuple of (cid, part_title, total_pages).

    Raises:
        SystemExit: If the video pagelist API request fails.
    """
    data = api_get(f"https://api.bilibili.com/x/player/pagelist?bvid={bvid}")
    if data.get("code") != 0 or not data.get("data"):
        print(f"Error: cannot get pagelist for {bvid}", file=sys.stderr)
        sys.exit(1)

    pages = data["data"]
    if page >= len(pages):
        page = 0

    cid = pages[page]["cid"]
    part_title = pages[page].get("part", "")
    return cid, part_title, len(pages)


def get_video_info(bvid: str) -> dict:
    """Fetch video metadata from the Bilibili API.

    Args:
        bvid: The 12-character BV ID of the video.

    Returns:
        Video metadata dictionary, or empty dict on failure.
    """
    data = api_get(f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}")
    if data.get("code") != 0:
        return {}
    return data.get("data", {})


def get_subtitle_url(bvid: str, cid: str, cookie: str = "") -> list:
    """Retrieve available subtitle URLs from the player API.

    Args:
        bvid: The 12-character BV ID of the video.
        cid: The CID of the video page.
        cookie: Optional Bilibili cookie for authenticated requests.

    Returns:
        A list of subtitle metadata dicts, or empty list if unavailable.
    """
    url = f"https://api.bilibili.com/x/player/v2?bvid={bvid}&cid={cid}"
    data = api_get(url, cookie)
    if data.get("code") != 0:
        return []
    return data.get("data", {}).get("subtitle", {}).get("subtitles", [])


def download_subtitle_json(subtitle_url: str) -> dict:
    """Download and parse a subtitle JSON file.

    Args:
        subtitle_url: The URL of the subtitle JSON resource.

    Returns:
        Parsed subtitle JSON as a dictionary with a 'body' key.

    Raises:
        urllib.error.URLError: If the download fails.
    """
    if subtitle_url.startswith("//"):
        subtitle_url = "https:" + subtitle_url
    req = urllib.request.Request(subtitle_url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_audio_url(bvid: str, cid: str) -> Optional[str]:
    """Get the audio stream URL from the Bilibili playurl API.

    Args:
        bvid: The 12-character BV ID of the video.
        cid: The CID of the video page.

    Returns:
        The audio stream base URL, or None if unavailable.
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
    """Download an audio stream to a local file using chunked reads.

    Args:
        audio_url: The audio stream URL.
        output_path: Local filesystem path to save the audio.
        referer: Optional HTTP Referer header value.

    Returns:
        True if the download succeeded, False otherwise.
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
            print(f"Downloaded {total} bytes", file=sys.stderr)
            return True
    except Exception as e:
        print(f"Download error: {e}", file=sys.stderr)
        return False