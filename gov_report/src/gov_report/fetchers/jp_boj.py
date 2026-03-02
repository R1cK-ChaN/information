"""BOJ fetcher — rate decisions, outlook report, summary of opinions.
Also covers Japan Cabinet Office (CAO) GDP flash estimate.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from gov_report.fetchers.base import BaseFetcher
from gov_report.models import FetchResult

_BOJ_BASE = "https://www.boj.or.jp"
_CAO_BASE = "https://www.esri.cao.go.jp"

_SOURCE_CONFIG = {
    "jp_boj_statement": {
        "listing_url": f"{_BOJ_BASE}/en/mopo/mpmdeci/index.htm",
        "rss_feed": f"{_BOJ_BASE}/rss/english/index.rss",
        "link_pattern": r"/en/mopo/mpmdeci/mpr_\d+/",
        "data_category": "monetary_policy",
        "institution": "Bank of Japan",
    },
    "jp_boj_outlook": {
        # Quarterly Outlook Report
        "listing_url": f"{_BOJ_BASE}/en/mopo/outlook/index.htm",
        "rss_feed": f"{_BOJ_BASE}/rss/english/index.rss",
        "link_pattern": r"/en/mopo/outlook/aar\d+",
        "data_category": "monetary_policy",
        "institution": "Bank of Japan",
    },
    "jp_boj_minutes": {
        # Summary of Opinions (published ~1 week after meeting)
        "listing_url": f"{_BOJ_BASE}/en/mopo/mpmsche_minu/opinion_",
        "rss_feed": f"{_BOJ_BASE}/rss/english/index.rss",
        "link_pattern": r"/en/mopo/mpmsche_minu/opinion_\d+/",
        "data_category": "monetary_policy",
        "institution": "Bank of Japan",
    },
    "jp_cao_gdp": {
        # Cabinet Office (内閣府) — GDP flash estimate (English page)
        "listing_url": f"{_CAO_BASE}/en/stat/di/di-e.html",
        "rss_feed": None,
        "link_pattern": r"/en/stat/di/",
        "data_category": "gdp",
        "institution": "Japan Cabinet Office",
    },
}

_CONTENT_SELECTORS = [
    "div#main",
    "div.releaseMain",
    "div.mb20",
    "article",
    "main",
]

_DATE_PATTERNS = [
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}",
    r"\d{4}/\d{2}/\d{2}",
    r"\d{4}-\d{2}-\d{2}",
]


class BOJFetcher(BaseFetcher):
    country = "JP"
    language = "en"

    @property
    def institution(self) -> str:  # type: ignore[override]
        cfg = _SOURCE_CONFIG.get(self.source_id, {})
        return cfg.get("institution", "Bank of Japan")

    async def fetch_latest(self) -> list[FetchResult]:
        cfg = _SOURCE_CONFIG.get(self.source_id)
        if not cfg:
            raise ValueError(f"No config for {self.source_id}")

        base = _CAO_BASE if self.source_id == "jp_cao_gdp" else _BOJ_BASE
        html = await self._get_html(cfg["listing_url"])
        soup = BeautifulSoup(html, "html.parser")
        pattern = cfg.get("link_pattern", "")

        for a in soup.find_all("a", href=True):
            if pattern and re.search(pattern, a["href"]):
                url = self._resolve_url(a["href"], base)
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
