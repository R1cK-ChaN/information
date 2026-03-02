"""Eurostat fetcher — euro area CPI (HICP), GDP, employment."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from gov_report.fetchers.base import BaseFetcher
from gov_report.models import FetchResult

_EUROSTAT_BASE = "https://ec.europa.eu/eurostat"

_SOURCE_CONFIG = {
    "eu_eurostat_cpi": {
        "listing_url": "https://ec.europa.eu/eurostat/news/news-releases",
        "rss_feed": "https://ec.europa.eu/eurostat/news/rss",
        "keywords": ["HICP", "inflation", "consumer price"],
        "data_category": "inflation",
    },
    "eu_eurostat_gdp": {
        "listing_url": "https://ec.europa.eu/eurostat/news/news-releases",
        "rss_feed": "https://ec.europa.eu/eurostat/news/rss",
        "keywords": ["GDP", "gross domestic product", "economic growth"],
        "data_category": "gdp",
    },
    "eu_eurostat_employment": {
        "listing_url": "https://ec.europa.eu/eurostat/news/news-releases",
        "rss_feed": "https://ec.europa.eu/eurostat/news/rss",
        "keywords": ["unemployment", "employment", "labour market"],
        "data_category": "employment",
    },
}

_CONTENT_SELECTORS = [
    "div.stat-news-release-content",
    "div.article-body",
    "div#main-content",
    "article",
    "main",
]

_DATE_PATTERNS = [
    r"\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}",
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}",
    r"\d{4}-\d{2}-\d{2}",
]


class EurostatFetcher(BaseFetcher):
    institution = "Eurostat"
    country = "EU"
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
            if any(kw in text for kw in keywords):
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
        for sel in ["h1.stat-news-release-title", "h1", "h2", "title"]:
            el = soup.select_one(sel)
            if el and el.get_text(strip=True):
                return el.get_text(strip=True)
        return self.source_id
