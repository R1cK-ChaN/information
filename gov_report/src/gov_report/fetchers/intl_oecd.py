"""OECD fetcher — Economic Outlook, country assessments, composite leading indicators."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from gov_report.fetchers.base import BaseFetcher
from gov_report.models import FetchResult

_OECD_BASE = "https://www.oecd.org"

_SOURCE_CONFIG = {
    "intl_oecd_outlook": {
        # Economic Outlook — semi-annual flagship
        "listing_url": f"{_OECD_BASE}/economic-outlook/",
        "rss_feed": f"{_OECD_BASE}/feed",
        "link_pattern": r"/economic-outlook/\d+/",
        "data_category": "global_outlook",
    },
    "intl_oecd_cli": {
        # Composite Leading Indicators — monthly
        "listing_url": f"{_OECD_BASE}/sdd/leading-indicators/",
        "rss_feed": f"{_OECD_BASE}/feed",
        "keywords": ["composite leading indicator", "CLI"],
        "data_category": "leading_indicators",
    },
    "intl_oecd_press": {
        "listing_url": f"{_OECD_BASE}/newsroom/",
        "rss_feed": f"{_OECD_BASE}/feed",
        "keywords": ["economic", "GDP", "inflation", "growth"],
        "link_pattern": r"/newsroom/.*\.htm",
        "data_category": "economic_conditions",
    },
}

_CONTENT_SELECTORS = [
    "div.main-content",
    "div.article-body",
    "div#content",
    "article",
    "main",
]

_DATE_PATTERNS = [
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}",
    r"\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}",
    r"\d{4}-\d{2}-\d{2}",
]


class OECDFetcher(BaseFetcher):
    institution = "OECD"
    country = "INT"
    language = "en"

    async def fetch_latest(self) -> list[FetchResult]:
        cfg = _SOURCE_CONFIG.get(self.source_id)
        if not cfg:
            raise ValueError(f"No config for {self.source_id}")

        html = await self._get_html(cfg["listing_url"])
        soup = BeautifulSoup(html, "html.parser")
        pattern = cfg.get("link_pattern", "")
        keywords = [kw.lower() for kw in cfg.get("keywords", [])]

        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True).lower()
            matched = (pattern and re.search(pattern, href)) or (
                keywords and any(kw in text for kw in keywords)
            )
            if matched:
                url = self._resolve_url(href, _OECD_BASE)
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
