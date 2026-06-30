"""Deterministic automatic tags derived from yt-dlp metadata."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

PLATFORM_TAGS = {"youtube", "twitch", "kick", "vimeo", "soundcloud"}
CODEC_ALIASES = {
    "avc1": "h264",
    "h264": "h264",
    "hev1": "h265",
    "h265": "h265",
    "vp09": "vp9",
    "vp9": "vp9",
    "av01": "av1",
    "av1": "av1",
}


def generate_auto_tags(
    url: str,
    download_type: str,
    metadata: dict[str, Any] | None = None,
    is_live: bool = False,
) -> list[str]:
    """Return stable automatic tags without mixing in manual user tags."""

    metadata = metadata or {}
    tags: list[str] = []

    platform = str(metadata.get("platform") or _platform_from_url(url) or "").casefold()
    if platform in PLATFORM_TAGS:
        _append(tags, platform)

    content_type = str(metadata.get("content_type") or "").casefold()
    live_status = str(metadata.get("live_status") or "").casefold()
    if is_live or content_type == "live" or live_status in {"is_live", "post_live"}:
        _append(tags, "live")
    elif content_type in {"playlist", "shorts"}:
        _append(tags, content_type)
    elif download_type == "audio":
        _append(tags, "audio")
    else:
        _append(tags, "video")

    if download_type == "audio":
        _append(tags, "audio")

    height = _height(metadata)
    if height:
        _append(tags, "4k" if height >= 2160 else f"{height}p")

    codec = _codec(metadata)
    if codec:
        _append(tags, codec)

    year = _year(metadata)
    if year:
        _append(tags, str(year))

    return tags


def _append(tags: list[str], value: str) -> None:
    tag = value.strip().casefold()
    if tag and tag not in tags:
        tags.append(tag)


def _platform_from_url(url: str) -> str:
    host = (urlsplit(url).hostname or "").casefold()
    for platform in PLATFORM_TAGS:
        if platform in host:
            return platform
    return ""


def _height(metadata: dict[str, Any]) -> int | None:
    for key in ("height", "requested_height"):
        value = _positive_int(metadata.get(key))
        if value:
            return _normalized_height(value)
    resolution = str(metadata.get("resolution") or "")
    match = re.search(r"(?:(?:x|/)|^)(\d{3,4})p?$", resolution)
    if match:
        return _normalized_height(int(match.group(1)))
    formats = metadata.get("requested_downloads") or metadata.get("formats") or []
    heights = [
        _positive_int(item.get("height"))
        for item in formats
        if isinstance(item, dict)
    ]
    heights = [item for item in heights if item]
    return _normalized_height(max(heights)) if heights else None


def _normalized_height(height: int) -> int:
    if height >= 2160:
        return 2160
    for common in (1440, 1080, 720, 480, 360, 240):
        if abs(height - common) <= 8 or height >= common:
            return common
    return height


def _codec(metadata: dict[str, Any]) -> str | None:
    candidates = [
        metadata.get("vcodec"),
        metadata.get("video_codec"),
        metadata.get("codec"),
    ]
    for item in metadata.get("requested_downloads") or []:
        if isinstance(item, dict):
            candidates.append(item.get("vcodec"))
    for candidate in candidates:
        text = str(candidate or "").casefold()
        if not text or text == "none":
            continue
        for marker, label in CODEC_ALIASES.items():
            if marker in text:
                return label
    return None


def _year(metadata: dict[str, Any]) -> int | None:
    for key in ("release_year", "release_date", "upload_date", "timestamp"):
        value = metadata.get(key)
        if key == "timestamp":
            continue
        text = str(value or "")
        match = re.match(r"^(20\d{2}|19\d{2})", text)
        if match:
            return int(match.group(1))
    return None


def _positive_int(value: object) -> int | None:
    try:
        number = int(float(str(value)))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
