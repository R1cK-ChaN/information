"""World Bank fetcher — Global Economic Prospects (GEP), development reports."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from gov_report.fetchers.base import BaseFetcher
from gov_report.models import FetchResult

_WB_BASE = "https://www.worldbank.org"

_SOURCE_CONFIG = {
    "intl_wb_gep": {
        # Global Economic Prospects — semi-annual flagship
        "listing_url": f"{_WB_BASE}/en/publication/global-economic-prospects",
        "rss_feed": f"{_WB_BASE}/en/rss",
        "link_pattern": r"/en/publication/global-economic-prospects",
        "data_category": "global_outlook",
    },
    "intl_wb_press": {
        "listing_url": f"{_WB_BASE}/en/news/press-releases",
        "rss_feed": f"{_WB_BASE}/en/rss",
        "link_pattern": r"/en/news/press-release/\d{4}/",
        "data_category": "development",
    },
}

_CONTENT_SELECTORS = [
    "div.body-content",
    "div#content-area",
    "div.publication-detail",
    "article",
    "main",
]

_DATE_PATTERNS = [
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}",
    r"\d{4}-\d{2}-\d{2}",
]


class WorldBankFetcher(BaseFetcher):
    institution = "World Bank"
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
                url = self._resolve_url(a["href"], _WB_BASE)
                if url != cfg["listing_url"]:
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
