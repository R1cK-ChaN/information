"""Generic URL fetcher with optional paywall fallback.

A thin wrapper around httpx that returns both the raw status and the decoded
text body. When a ``PaywallFetcher`` is passed in, a 4xx response triggers the
paywall path (Playwright + Wayback) the same way the RSS pipeline handles
blocked articles.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class FetchResult:
    url: str
    status: int
    text: str
    via_paywall: bool = False
    error: str | None = None


def fetch_url(
    url: str,
    *,
    timeout: float = 20.0,
    paywall_fetcher=None,
    max_chars: int = 120_000,
) -> FetchResult:
    """GET *url* and return the decoded body text.

    On a 4xx response *and* when *paywall_fetcher* is supplied, retry via the
    paywall path (reuses the Playwright + Wayback helper already in
    ``news.src.rss.paywall_fetcher``).
    """
    try:
        resp = httpx.get(
            url,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        )
    except httpx.HTTPError as exc:
        return FetchResult(url=url, status=0, text="", error=str(exc))

    if resp.status_code < 400:
        return FetchResult(url=url, status=resp.status_code, text=resp.text[:max_chars])

    if paywall_fetcher is None:
        return FetchResult(
            url=url,
            status=resp.status_code,
            text="",
            error=f"HTTP {resp.status_code}",
        )

    try:
        article = paywall_fetcher.fetch_article(url, "")
    except Exception as exc:  # pragma: no cover — defensive, paywall path is best-effort
        return FetchResult(
            url=url, status=resp.status_code, text="", error=f"paywall: {exc}"
        )

    return FetchResult(
        url=url,
        status=resp.status_code,
        text=(getattr(article, "content", "") or "")[:max_chars],
        via_paywall=True,
    )
