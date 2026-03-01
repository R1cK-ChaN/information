"""Census Bureau fetcher — Retail Sales, Housing Starts."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from gov_report.fetchers.base import BaseFetcher
from gov_report.models import FetchResult

_SOURCE_CONFIG = {
    "us_census_retail": {
        "listing_url": "https://www.census.gov/retail/index.html",
        "keywords": ["retail", "advance monthly sales"],
        "data_category": "consumption",
    },
    "us_census_housing": {
        "listing_url": "https://www.census.gov/construction/nrc/index.html",
        "keywords": ["housing", "new residential", "building permits"],
        "data_category": "housing",
    },
}

_CONTENT_SELECTORS = [
    ".press-release",
    "#content",
    "article",
    ".uscb-layout-column-2",
]

_DATE_PATTERNS = [
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}",
    r"\d{4}-\d{2}-\d{2}",
]


class CensusFetcher(BaseFetcher):
    institution = "Census Bureau"
    country = "US"
    language = "en"

    async def fetch_latest(self) -> list[FetchResult]:
        cfg = _SOURCE_CONFIG.get(self.source_id)
        if not cfg:
            raise ValueError(f"No config for {self.source_id}")

        html = await self._get_html(cfg["listing_url"])
        soup = BeautifulSoup(html, "html.parser")
        keywords = cfg["keywords"]

        # Look for the latest press release link
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True).lower()
            href = a["href"]
            if any(kw in text for kw in keywords) or ".pdf" in href:
                url = href
                if not url.startswith("http"):
                    url = "https://www.census.gov" + url
                if url.endswith(".pdf"):
                    # PDF release — fetch bytes
                    try:
                        return [await self._fetch_pdf(url, cfg)]
                    except Exception:
                        continue
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

    async def _fetch_pdf(self, url: str, cfg: dict) -> FetchResult:
        pdf_bytes = await self._get_bytes(url)
        return self._make_result(
            url=url,
            title=self.source_id,
            publish_date="",
            content_html="",
            content_type="pdf",
            pdf_bytes=pdf_bytes,
            data_category=cfg.get("data_category", ""),
        )

    def _extract_title(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for sel in ["h1", "h2", "title"]:
            el = soup.select_one(sel)
            if el and el.get_text(strip=True):
                return el.get_text(strip=True)
        return self.source_id
