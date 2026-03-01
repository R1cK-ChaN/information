"""Base fetcher ABC with shared HTTP and parsing helpers."""

from __future__ import annotations

import abc
import logging
import re
from typing import TYPE_CHECKING

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from gov_report.models import FetchResult

if TYPE_CHECKING:
    from gov_report.config import Settings

logger = logging.getLogger(__name__)


class BaseFetcher(abc.ABC):
    """Abstract base for institution-specific fetchers."""

    institution: str = ""
    country: str = ""  # "US" | "CN"
    language: str = ""  # "en" | "zh"

    def __init__(self, settings: Settings, source_id: str) -> None:
        self.settings = settings
        self.source_id = source_id

    @abc.abstractmethod
    async def fetch_latest(self) -> list[FetchResult]:
        """Scrape the latest report(s) for this source_id."""

    async def fetch_by_url(self, url: str) -> FetchResult:
        """Fetch a specific report by URL (for RSS/calendar triggers).

        Subclasses should override if they need special per-URL handling.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support fetch_by_url"
        )

    # -- shared helpers -------------------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=10),
        reraise=True,
    )
    async def _get_html(self, url: str, *, encoding: str | None = None) -> str:
        """GET a URL and return decoded HTML text."""
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self.settings.request_timeout, connect=10.0),
            headers={"User-Agent": self.settings.user_agent},
            follow_redirects=True,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            if encoding:
                resp.encoding = encoding
            return resp.text

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=10),
        reraise=True,
    )
    async def _get_bytes(self, url: str) -> bytes:
        """GET a URL and return raw bytes (for PDFs)."""
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self.settings.request_timeout, connect=10.0),
            headers={"User-Agent": self.settings.user_agent},
            follow_redirects=True,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content

    def _extract_content(
        self, html: str, selectors: list[str], *, remove: list[str] | None = None
    ) -> str:
        """Extract content HTML using CSS selector priority list.

        Tries each selector in order; returns the first match's inner HTML.
        Falls back to <body> if no selector matches.
        """
        soup = BeautifulSoup(html, "html.parser")

        # Remove noise elements
        for tag in soup.find_all(["script", "style", "nav", "noscript"]):
            tag.decompose()
        if remove:
            for sel in remove:
                for el in soup.select(sel):
                    el.decompose()

        for sel in selectors:
            el = soup.select_one(sel)
            if el:
                return str(el)

        # Fallback: body
        body = soup.find("body")
        return str(body) if body else html

    def _extract_date(self, html: str, patterns: list[str]) -> str | None:
        """Extract a publication date from HTML using regex patterns.

        Returns ISO date string (YYYY-MM-DD) or None.
        """
        for pat in patterns:
            m = re.search(pat, html)
            if m:
                return self._normalize_date(m.group(0))
        return None

    def _normalize_date(self, raw: str) -> str:
        """Best-effort date normalization to YYYY-MM-DD."""
        from dateutil.parser import parse as dateparse

        try:
            return dateparse(raw, fuzzy=True).strftime("%Y-%m-%d")
        except (ValueError, OverflowError):
            return raw

    def _make_result(
        self,
        url: str,
        title: str,
        publish_date: str,
        content_html: str,
        *,
        data_category: str = "",
        content_type: str = "html",
        pdf_bytes: bytes | None = None,
        metadata: dict | None = None,
    ) -> FetchResult:
        """Convenience builder for FetchResult."""
        return FetchResult(
            url=url,
            title=title,
            publish_date=publish_date,
            content_html=content_html,
            content_type=content_type,
            source_id=self.source_id,
            institution=self.institution,
            country=self.country,
            language=self.language,
            data_category=data_category,
            pdf_bytes=pdf_bytes,
            metadata=metadata or {},
        )
