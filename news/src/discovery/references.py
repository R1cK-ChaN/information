"""Extract external URLs from a markdown body.

Used by the newsletter parser to surface referenced sources so an ingestion
script can chase them via ``discovery.fetch_url``. Extraction is pure — no
network — so parsers can call it unconditionally.
"""

from __future__ import annotations

import re

_URL_RE = re.compile(
    r"https?://[^\s<>()\"']+[^\s<>()\"'.,;:!?]",
    re.IGNORECASE,
)


def extract_urls(markdown: str, *, limit: int | None = None) -> list[str]:
    """Return unique http(s) URLs from *markdown*, in first-seen order."""
    if not markdown:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for match in _URL_RE.finditer(markdown):
        url = match.group(0)
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
        if limit is not None and len(out) >= limit:
            break
    return out
