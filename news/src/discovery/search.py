"""Web search wrapper over the Brave Search API.

Off when ``BRAVE_API_KEY`` is unset — ``search()`` returns an empty list so
callers can unconditionally invoke it during ingestion without gating on
env presence.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
_API_KEY_ENV = "BRAVE_API_KEY"


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


def search(query: str, *, limit: int = 5, timeout: float = 10.0) -> list[SearchResult]:
    """Return up to *limit* web results for *query*. Empty list if the API
    key is unset, the call errors, or the query is blank."""
    if not query or not query.strip():
        return []
    api_key = os.getenv(_API_KEY_ENV)
    if not api_key:
        logger.debug("discovery.search: %s not set; skipping", _API_KEY_ENV)
        return []

    try:
        resp = httpx.get(
            _BRAVE_ENDPOINT,
            params={"q": query, "count": limit},
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": api_key,
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        # ValueError covers resp.json() failures when Brave returns a 200 with
        # a non-JSON body (CDN error page, rate-limit HTML, etc).
        logger.warning("discovery.search failed for %r: %s", query, exc)
        return []

    web = payload.get("web") or {}
    results = web.get("results") or []
    return [
        SearchResult(
            title=r.get("title") or "",
            url=r.get("url") or "",
            snippet=r.get("description") or "",
        )
        for r in results[:limit]
        if r.get("url")
    ]
