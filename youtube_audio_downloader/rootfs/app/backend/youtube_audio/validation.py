"""Strict YouTube URL parsing."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

from .errors import AppError

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{6,20}$")
_WATCH_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}
_SHORT_HOSTS = {"youtu.be", "www.youtu.be"}


def parse_youtube_url(value: str) -> tuple[str, str]:
    if len(value) > 2_048:
        raise AppError("invalid_url", "The URL is too long.")
    try:
        parts = urlsplit(value)
    except ValueError as exc:
        raise AppError("invalid_url", "The provided URL is not valid.") from exc
    if parts.scheme != "https" or parts.username or parts.password or parts.port:
        raise AppError("invalid_url", "Only standard HTTPS YouTube URLs are supported.")
    host = (parts.hostname or "").lower().rstrip(".")
    video_id: str | None = None
    if host in _SHORT_HOSTS:
        video_id = parts.path.strip("/").split("/", 1)[0]
    elif host in _WATCH_HOSTS:
        if parts.path.rstrip("/") == "/watch":
            video_id = parse_qs(parts.query).get("v", [None])[0]
        elif parts.path.startswith("/shorts/"):
            video_id = parts.path.split("/", 3)[2]
        elif parts.path.startswith("/embed/"):
            video_id = parts.path.split("/", 3)[2]
    else:
        raise AppError("unsupported_host", "The URL host is not a supported YouTube host.")
    if video_id is None or not _VIDEO_ID.fullmatch(video_id):
        raise AppError("invalid_url", "The URL does not contain a valid YouTube video ID.")
    canonical = f"https://www.youtube.com/watch?v={video_id}"
    return canonical, video_id
