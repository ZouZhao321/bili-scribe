"""Video info endpoint — query Bilibili video metadata without transcribing."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from src.core.bilibili import (
    api_get,
    extract_bvid,
    get_video_info,
    get_cid,
    get_subtitle_url,
)

from src.web.models import PageInfo, VideoInfoResponse

router = APIRouter(tags=["video"])


def _format_duration(seconds: int) -> str:
    """Convert a duration in seconds to MM:SS or HH:MM:SS format.

    Args:
        seconds: Duration in seconds.

    Returns:
        Formatted duration string (e.g. "5:11" or "1:05:11").
    """
    if seconds <= 0:
        return "0:00"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


@router.get("/video/info", response_model=VideoInfoResponse)
async def video_info(url: str = Query(..., description="B站视频链接或BV号")):
    """Get video metadata without transcribing.

    Fetches video title, author, duration, cover, description, page list,
    and subtitle availability from the Bilibili API.

    Args:
        url: Bilibili video URL, BV ID, or av number.

    Returns:
        VideoInfoResponse with all available metadata.

    Raises:
        HTTPException 400: If the URL is invalid.
        HTTPException 404: If the video does not exist.
    """
    try:
        bvid = extract_bvid(url)
    except SystemExit:
        raise HTTPException(status_code=400, detail={"error": "invalid_url", "message": f"无法解析 URL: {url}"})

    video_data = get_video_info(bvid)
    if not video_data:
        raise HTTPException(status_code=404, detail={
            "error": "video_not_found",
            "message": f"视频不存在或已删除: {bvid}",
        })

    title = video_data.get("title", bvid)
    author = video_data.get("owner", {}).get("name", "")
    duration = video_data.get("duration", 0)
    cover = video_data.get("pic", "")
    description = video_data.get("desc", "")

    # Get page list
    try:
        cid, _, total_pages = get_cid(bvid, 0)
    except SystemExit:
        cid, total_pages = 0, 1

    # Build page list
    pages_data = video_data.get("pages", [])
    pages = []
    for p in pages_data:
        pages.append(PageInfo(
            page=p.get("page", 0),
            part=p.get("part", ""),
            cid=p.get("cid", 0),
        ))

    # Check subtitle availability
    has_subtitle = False
    subtitle_languages = []
    try:
        sub_list = get_subtitle_url(bvid, str(cid)) if cid else []
        if sub_list:
            has_subtitle = True
            subtitle_languages = [s.get("lan_doc", s.get("lan", "unknown")) for s in sub_list]
    except Exception:
        pass

    return VideoInfoResponse(
        bvid=bvid,
        title=title,
        author=author,
        duration=duration,
        duration_formatted=_format_duration(duration),
        cover=cover,
        description=description,
        total_pages=total_pages if total_pages else len(pages),
        pages=pages,
        has_subtitle=has_subtitle,
        subtitle_languages=subtitle_languages,
    )