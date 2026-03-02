"""ONS fetcher — UK CPI, GDP, employment."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from gov_report.fetchers.base import BaseFetcher
from gov_report.models import FetchResult

_ONS_BASE = "https://www.ons.gov.uk"

_SOURCE_CONFIG = {
    "uk_ons_cpi": {
        "listing_url": f"{_ONS_BASE}/economy/inflationandpriceindices",
        "rss_feed": f"{_ONS_BASE}/feed",
        "keywords": ["consumer price inflation", "CPI", "CPIH"],
        "link_pattern": r"/economy/inflationandpriceindices/bulletins/consumerpriceinflation/",
        "data_category": "inflation",
    },
    "uk_ons_gdp": {
        "listing_url": f"{_ONS_BASE}/economy/grossdomesticproductgdp",
        "rss_feed": f"{_ONS_BASE}/feed",
        "keywords": ["GDP", "gross domestic product"],
        "link_pattern": r"/economy/grossdomesticproductgdp/bulletins/",
        "data_category": "gdp",
    },
    "uk_ons_employment": {
        "listing_url": f"{_ONS_BASE}/employmentandlabourmarket/peopleinwork",
        "rss_feed": f"{_ONS_BASE}/feed",
        "keywords": ["employment", "labour market", "unemployment"],
        "link_pattern": r"/employmentandlabourmarket/peopleinwork/employmentandemployeetypes/bulletins/",
        "data_category": "employment",
    },
}

_CONTENT_SELECTORS = [
    "div.page-content",
    "section.section-content",
    "div#main-content",
    "article",
    "main",
]

_DATE_PATTERNS = [
    r"\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}",
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}",
    r"\d{4}-\d{2}-\d{2}",
]


class ONSFetcher(BaseFetcher):
    institution = "ONS"
    country = "GB"
    language = "en"

    async def fetch_latest(self) -> list[FetchResult]:
        cfg = _SOURCE_CONFIG.get(self.source_id)
        if not cfg:
            raise ValueError(f"No config for {self.source_id}")

        html = await self._get_html(cfg["listing_url"])
        soup = BeautifulSoup(html, "html.parser")
        pattern = cfg.get("link_pattern", "")

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if pattern and re.search(pattern, href):
                url = self._resolve_url(href, _ONS_BASE)
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
