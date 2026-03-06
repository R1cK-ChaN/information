"""IMF fetcher — World Economic Outlook (WEO), Article IV consultations."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from gov_report.fetchers.base import BaseFetcher
from gov_report.models import FetchResult

_IMF_BASE = "https://www.imf.org"

_SOURCE_CONFIG = {
    "intl_imf_weo": {
        "listing_url": f"{_IMF_BASE}/en/Publications/WEO",
        "rss_feed": f"{_IMF_BASE}/en/rss",
        "link_pattern": r"/en/Publications/WEO/Issues/\d{4}/",
        "data_category": "global_outlook",
    },
    "intl_imf_gfsr": {
        # Global Financial Stability Report
        "listing_url": f"{_IMF_BASE}/en/Publications/GFSR",
        "rss_feed": f"{_IMF_BASE}/en/rss",
        "link_pattern": r"/en/Publications/GFSR/Issues/\d{4}/",
        "data_category": "financial_stability",
    },
    "intl_imf_press": {
        # Press releases / Article IV
        "listing_url": f"{_IMF_BASE}/en/News/Articles",
        "rss_feed": f"{_IMF_BASE}/en/rss",
        "link_pattern": r"/en/News/Articles/\d{4}/",
        "data_category": "policy_assessment",
    },
}

_CONTENT_SELECTORS = [
    "div.imf-article-body",
    "div.main-content",
    "div#content",
    "article",
    "main",
]

_DATE_PATTERNS = [
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}",
    r"\d{4}-\d{2}-\d{2}",
]


class IMFFetcher(BaseFetcher):
    institution = "IMF"
    country = "INT"
    language = "en"

    async def fetch_latest(self) -> list[FetchResult]:
        cfg = _SOURCE_CONFIG.get(self.source_id)
        if not cfg:
            raise ValueError(f"No config for {self.source_id}")

        html = await self._get_html(cfg["listing_url"])
        soup = BeautifulSoup(html, "html.parser")
        pattern = cfg.get("link_pattern", "")

        for a in soup.find_all("a", href=True):
            if pattern and re.search(pattern, a["href"]):
                url = self._resolve_url(a["href"], _IMF_BASE)
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
        for sel in ["h1.imf-article-title", "h1", "h2", "title"]:
            el = soup.select_one(sel)
            if el and el.get_text(strip=True):
                return el.get_text(strip=True)
        return self.source_id
