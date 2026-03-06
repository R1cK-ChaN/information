"""Bank of England fetcher — rate decisions, MPC minutes, MPR."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from gov_report.fetchers.base import BaseFetcher
from gov_report.models import FetchResult

_BOE_BASE = "https://www.bankofengland.co.uk"

_SOURCE_CONFIG = {
    "uk_boe_rate": {
        "listing_url": f"{_BOE_BASE}/monetary-policy/monetary-policy-committee",
        "rss_feed": f"{_BOE_BASE}/rss.xml",
        "link_pattern": r"/monetary-policy/monetary-policy-committee/mpc-decision",
        "data_category": "monetary_policy",
    },
    "uk_boe_minutes": {
        "listing_url": f"{_BOE_BASE}/monetary-policy/monetary-policy-committee",
        "rss_feed": f"{_BOE_BASE}/rss.xml",
        "link_pattern": r"/monetary-policy/monetary-policy-committee/.*minutes",
        "data_category": "monetary_policy",
    },
    "uk_boe_mpr": {
        # Monetary Policy Report — quarterly
        "listing_url": f"{_BOE_BASE}/monetary-policy-report",
        "rss_feed": f"{_BOE_BASE}/rss.xml",
        "link_pattern": r"/monetary-policy-report/\d{4}/",
        "data_category": "monetary_policy",
    },
}

_CONTENT_SELECTORS = [
    "div.page-content",
    "div.release-content",
    "main article",
    "div#content",
    "article",
    "main",
]

_DATE_PATTERNS = [
    r"\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}",
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}",
    r"\d{4}-\d{2}-\d{2}",
]


class BOEFetcher(BaseFetcher):
    institution = "Bank of England"
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
            if pattern and re.search(pattern, a["href"]):
                url = self._resolve_url(a["href"], _BOE_BASE)
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
        for sel in ["h1.page-title", "h1", "h2", "title"]:
            el = soup.select_one(sel)
            if el and el.get_text(strip=True):
                return el.get_text(strip=True)
        return self.source_id
