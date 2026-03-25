from __future__ import annotations

import re

URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)


def extract_urls(text: str) -> list[str]:
    if not text:
        return []
    return [match.group(0).rstrip(".,)") for match in URL_RE.finditer(text)]
