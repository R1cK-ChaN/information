"""BLS fetcher — CPI, PPI, Employment Situation (NFP)."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from gov_report.fetchers.base import BaseFetcher
from gov_report.models import FetchResult

# Fixed "latest" URLs for key BLS releases
_LATEST_URLS = {
    "us_bls_cpi": "https://www.bls.gov/news.release/cpi.htm",
    "us_bls_ppi": "https://www.bls.gov/news.release/ppi.htm",
    "us_bls_nfp": "https://www.bls.gov/news.release/empsit.htm",
}

_DATA_CATEGORIES = {
    "us_bls_cpi": "inflation",
    "us_bls_ppi": "inflation",
    "us_bls_nfp": "employment",
}

_CONTENT_SELECTORS = [
    "#news-release",
    ".news-release-intro",
    "#bodytext",
    "div.body-content",
]

_DATE_PATTERNS = [
    r"(?:Released|Issued|Published)\s+\w+\s+\d{1,2},?\s+\d{4}",
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}",
]


class BLSFetcher(BaseFetcher):
    institution = "BLS"
    country = "US"
    language = "en"

    async def fetch_latest(self) -> list[FetchResult]:
        url = _LATEST_URLS.get(self.source_id)
        if not url:
            raise ValueError(f"No URL configured for {self.source_id}")
        return [await self.fetch_by_url(url)]

    async def fetch_by_url(self, url: str) -> FetchResult:
        html = await self._get_html(url)
        content = self._extract_content(html, _CONTENT_SELECTORS)
        title = self._extract_title(html)
        pub_date = self._extract_date(html, _DATE_PATTERNS) or ""
        return self._make_result(
            url=url,
            title=title,
            publish_date=pub_date,
            content_html=content,
            data_category=_DATA_CATEGORIES.get(self.source_id, ""),
        )

    def _extract_title(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        # BLS titles are in h2 or h3 within news release
        for sel in ["#news-release h2", "#news-release h3", "h1", "title"]:
            el = soup.select_one(sel)
            if el and el.get_text(strip=True):
                return el.get_text(strip=True)
        return self.source_id
