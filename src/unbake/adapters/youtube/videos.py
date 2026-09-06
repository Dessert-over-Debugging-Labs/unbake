"""영상 메타 조회 — videos.list 1회 (1 unit)."""

import re

import requests

_API = "https://www.googleapis.com/youtube/v3/videos"
_DUR = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def parse_iso8601_ms(duration: str) -> int | None:
    match = _DUR.fullmatch(duration or "")
    if not match:
        return None
    hours, minutes, seconds = (int(g or 0) for g in match.groups())
    return (hours * 3600 + minutes * 60 + seconds) * 1000


def get_video_meta(api_key: str, video_id: str) -> dict | None:
    """{videoId, title, description, durationMs, channelId, channelTitle} 또는 None."""
    res = requests.get(
        _API,
        params={
            "key": api_key,
            "id": video_id,
            "part": "snippet,contentDetails",
        },
        timeout=30,
    )
    res.raise_for_status()
    items = res.json().get("items", [])
    if not items:
        return None
    snippet = items[0].get("snippet", {})
    details = items[0].get("contentDetails", {})
    return {
        "videoId": video_id,
        "title": snippet.get("title", ""),
        "description": snippet.get("description", ""),
        "durationMs": parse_iso8601_ms(details.get("duration", "")),
        "channelId": snippet.get("channelId", ""),
        "channelTitle": snippet.get("channelTitle", ""),
    }
