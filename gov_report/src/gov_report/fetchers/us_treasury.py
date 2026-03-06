"""US Treasury fetcher — TIC capital flows, debt/fiscal statements."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from gov_report.fetchers.base import BaseFetcher
from gov_report.models import FetchResult

_SOURCE_CONFIG = {
    "us_treasury_tic": {
        "listing_url": "https://home.treasury.gov/data/treasury-international-capital-tic-system",
        "rss_feed": "https://home.treasury.gov/news/rss.xml",
        "keywords": ["TIC", "treasury international capital", "capital flow"],
        "data_category": "capital_flows",
    },
    "us_treasury_debt": {
        "listing_url": "https://home.treasury.gov/news/press-releases",
        "rss_feed": "https://home.treasury.gov/news/rss.xml",
        "keywords": ["debt", "deficit", "fiscal", "budget"],
        "data_category": "fiscal_policy",
    },
}

_CONTENT_SELECTORS = [
    "div.field--name-body",
    "div.field--type-text-with-summary",
    "article",
    "main#content",
    "div.views-row",
]

_DATE_PATTERNS = [
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}",
    r"\d{4}-\d{2}-\d{2}",
]


class TreasuryFetcher(BaseFetcher):
    institution = "US Treasury"
    country = "US"
    language = "en"

    async def fetch_latest(self) -> list[FetchResult]:
        cfg = _SOURCE_CONFIG.get(self.source_id)
        if not cfg:
            raise ValueError(f"No config for {self.source_id}")

        html = await self._get_html(cfg["listing_url"])
        soup = BeautifulSoup(html, "html.parser")
        keywords = [kw.lower() for kw in cfg["keywords"]]

        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True).lower()
            href = a["href"].lower()
            if any(kw in text or kw in href for kw in keywords):
                url = self._resolve_url(a["href"], cfg["listing_url"])
                if url.startswith("http"):
                    try:
                        return [await self.fetch_by_url(url)]
                    except Exception:
                        continue
        return []

    async def fetch_by_url(self, url: str) -> FetchResult:
        html = await self._get_html(url)
        content = self._extract_content(html, _CONTENT_SELECTORS)
        title = self._extract_title(html)
        pub_date = self._extract_date(html, _DATE_PATTERNS) or ""
        cfg = _SOURCE_CONFIG.get(self.source_id, {})
        return self._make_result(
            url=url,
            title=title,
            publish_date=pub_date,
            content_html=content,
            data_category=cfg.get("data_category", ""),
        )

    def _extract_title(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for sel in ["h1", "h2", "title"]:
            el = soup.select_one(sel)
            if el and el.get_text(strip=True):
                return el.get_text(strip=True)
        return self.source_id
