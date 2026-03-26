from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
}
YOUTU_BE_HOSTS = {"youtu.be", "www.youtu.be"}


def extract_urls(text: str) -> list[str]:
    if not text:
        return []
    return [match.group(0).rstrip(".,)") for match in URL_RE.finditer(text)]


def normalize_source_url(url: str) -> str:
    if not url:
        return url

    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host in YOUTU_BE_HOSTS:
        video_id = parsed.path.lstrip("/").split("/", 1)[0]
        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"
        return url

    if host not in YOUTUBE_HOSTS:
        return url

    if parsed.path == "/watch":
        video_id = parse_qs(parsed.query).get("v", [None])[0]
        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"
        return url

    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) >= 2 and path_parts[0] in {"shorts", "live"}:
        return f"https://www.youtube.com/watch?v={path_parts[1]}"

    return url
