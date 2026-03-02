"""BIS fetcher — Quarterly Review, working papers, monetary policy research."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from gov_report.fetchers.base import BaseFetcher
from gov_report.models import FetchResult

_BIS_BASE = "https://www.bis.org"

_SOURCE_CONFIG = {
    "intl_bis_quarterly": {
        "listing_url": f"{_BIS_BASE}/publ/quarterly.htm",
        "rss_feed": f"{_BIS_BASE}/rss.htm",
        "link_pattern": r"/publ/qtrpdf/r_qt\d+\.htm",
        "data_category": "financial_markets",
    },
    "intl_bis_research": {
        # BIS Working Papers — monetary/macro research
        "listing_url": f"{_BIS_BASE}/publ/work.htm",
        "rss_feed": f"{_BIS_BASE}/rss.htm",
        "link_pattern": r"/publ/work\d+\.htm",
        "data_category": "research",
    },
    "intl_bis_speech": {
        # Central banker speeches from BIS repository
        "listing_url": f"{_BIS_BASE}/cbspeeches/index.htm",
        "rss_feed": f"{_BIS_BASE}/rss.htm",
        "link_pattern": r"/review/r\d+[a-z]+\.htm",
        "data_category": "monetary_policy",
    },
}

_CONTENT_SELECTORS = [
    "div#containerwrap",
    "div.bigreference",
    "div#content",
    "article",
    "main",
]

_DATE_PATTERNS = [
    r"\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}",
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}",
    r"\d{4}-\d{2}-\d{2}",
]


class BISFetcher(BaseFetcher):
    institution = "BIS"
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
                url = self._resolve_url(a["href"], _BIS_BASE)
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
