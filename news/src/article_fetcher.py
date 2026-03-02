"""Fetch full article content from URLs and convert to markdown."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from readability import Document
from markdownify import markdownify

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class ArticleContent:
    content: str
    fetched: bool
    content_length: int
    error: str | None = None


class ArticleFetcher:
    """Fetch and extract readable article content from URLs."""

    def __init__(
        self,
        timeout: int = 20,
        max_content_chars: int = 15_000,
    ):
        self._timeout = timeout
        self._max_content_chars = max_content_chars
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        )

    @staticmethod
    def _is_google_news_url(url: str) -> bool:
        """Google News proxy URLs use JS redirects that can't be resolved."""
        try:
            return urlparse(url).hostname == "news.google.com"
        except Exception:
            return False

    def fetch_article(self, url: str, rss_description: str) -> ArticleContent:
        """Fetch full article content from *url*.

        Returns extracted markdown on success, or *rss_description* as
        fallback on any error — never loses content.
        """
        if self._is_google_news_url(url):
            return ArticleContent(
                content=rss_description,
                fetched=False,
                content_length=len(rss_description),
                error="skipped: Google News proxy URL",
            )

        try:
            resp = self._client.get(url)
            resp.raise_for_status()

            doc = Document(resp.text)
            html_summary = doc.summary()
            text = markdownify(html_summary).strip()

            if not text:
                return ArticleContent(
                    content=rss_description,
                    fetched=False,
                    content_length=len(rss_description),
                    error="readability produced empty output",
                )

            if len(text) > self._max_content_chars:
                text = text[: self._max_content_chars]

            return ArticleContent(
                content=text,
                fetched=True,
                content_length=len(text),
            )

        except Exception as exc:
            logger.debug("Article fetch failed for %s: %s", url, exc)
            return ArticleContent(
                content=rss_description,
                fetched=False,
                content_length=len(rss_description),
                error=str(exc),
            )

    def close(self):
        self._client.close()
