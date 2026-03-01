"""ISM fetcher — Manufacturing and Services PMI."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from gov_report.fetchers.base import BaseFetcher
from gov_report.models import FetchResult

_SOURCE_CONFIG = {
    "us_ism_manufacturing": {
        "listing_url": "https://www.ismworld.org/supply-management-news-and-reports/reports/ism-report-on-business/pmi/pmi-archive/",
        "keywords": ["manufacturing", "pmi"],
        "data_category": "manufacturing",
    },
    "us_ism_services": {
        "listing_url": "https://www.ismworld.org/supply-management-news-and-reports/reports/ism-report-on-business/services/services-pmi-archive/",
        "keywords": ["services", "non-manufacturing"],
        "data_category": "services",
    },
}

_CONTENT_SELECTORS = [
    ".content-area",
    "article",
    ".main-content",
    "#content",
]

_DATE_PATTERNS = [
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}",
    r"\d{4}-\d{2}-\d{2}",
]


class ISMFetcher(BaseFetcher):
    institution = "ISM"
    country = "US"
    language = "en"

    async def fetch_latest(self) -> list[FetchResult]:
        cfg = _SOURCE_CONFIG.get(self.source_id)
        if not cfg:
            raise ValueError(f"No config for {self.source_id}")

        html = await self._get_html(cfg["listing_url"])
        soup = BeautifulSoup(html, "html.parser")

        # Find the most recent report link
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True).lower()
            if any(kw in text for kw in cfg["keywords"]) or "report" in text.lower():
                url = href
                if not url.startswith("http"):
                    url = "https://www.ismworld.org" + url
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
