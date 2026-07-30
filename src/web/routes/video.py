"""视频信息端点 — 查询 B 站视频元数据，不进行转录。"""

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
    """将秒数转换为 MM:SS 或 HH:MM:SS 格式。

    参数：
        seconds: 时长（秒）。

    返回：
        格式化后的时长字符串（如 "5:11" 或 "1:05:11"）。
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
    """获取视频元数据，不进行转录。

    从 B 站 API 获取视频标题、作者、时长、封面、描述、分 P 列表
    和字幕可用性信息。

    参数：
        url: B 站视频链接、BV ID 或 av 号。

    返回：
        包含所有可用元数据的 VideoInfoResponse。

    抛出：
        HTTPException 400: 如果 URL 无效。
        HTTPException 404: 如果视频不存在。
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

    # 获取分 P 列表
    try:
        cid, _, total_pages = get_cid(bvid, 0)
    except SystemExit:
        cid, total_pages = 0, 1

    # 构建页面列表
    pages_data = video_data.get("pages", [])
    pages = []
    for p in pages_data:
        pages.append(PageInfo(
            page=p.get("page", 0),
            part=p.get("part", ""),
            cid=p.get("cid", 0),
        ))

    # 检查字幕可用性
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