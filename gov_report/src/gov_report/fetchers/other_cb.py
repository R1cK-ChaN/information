"""Other major central bank fetchers — RBA, BOC, SNB, Riksbank.

All four follow the same simple RSS + press release listing pattern.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from gov_report.fetchers.base import BaseFetcher
from gov_report.models import FetchResult

_SOURCE_CONFIG = {
    # --- Australia: Reserve Bank of Australia ---
    "au_rba_statement": {
        "listing_url": "https://www.rba.gov.au/monetary-policy/rba-board-minutes/",
        "rss_feed": "https://www.rba.gov.au/rss.xml",
        "link_pattern": r"/monetary-policy/rba-board-minutes/\d{4}/",
        "data_category": "monetary_policy",
        "institution": "Reserve Bank of Australia",
        "country": "AU",
        "base_url": "https://www.rba.gov.au",
    },
    "au_rba_rate": {
        "listing_url": "https://www.rba.gov.au/monetary-policy/cash-rate-target.html",
        "rss_feed": "https://www.rba.gov.au/rss.xml",
        "link_pattern": r"/media-releases/\d{4}/mr-\d+\.html",
        "data_category": "monetary_policy",
        "institution": "Reserve Bank of Australia",
        "country": "AU",
        "base_url": "https://www.rba.gov.au",
    },
    # --- Canada: Bank of Canada ---
    "ca_boc_statement": {
        "listing_url": "https://www.bankofcanada.ca/core-functions/monetary-policy/key-interest-rate/",
        "rss_feed": "https://www.bankofcanada.ca/rss",
        "link_pattern": r"/\d{4}/\d{2}/fad-press-release",
        "data_category": "monetary_policy",
        "institution": "Bank of Canada",
        "country": "CA",
        "base_url": "https://www.bankofcanada.ca",
    },
    "ca_boc_mpr": {
        # Monetary Policy Report — quarterly
        "listing_url": "https://www.bankofcanada.ca/publications/mpr/",
        "rss_feed": "https://www.bankofcanada.ca/rss",
        "link_pattern": r"/\d{4}/\d{2}/monetary-policy-report",
        "data_category": "monetary_policy",
        "institution": "Bank of Canada",
        "country": "CA",
        "base_url": "https://www.bankofcanada.ca",
    },
    # --- Switzerland: Swiss National Bank ---
    "ch_snb_statement": {
        "listing_url": "https://www.snb.ch/en/publications/communication/press-releases/id/press_releases",
        "rss_feed": "https://www.snb.ch/rss/en",
        "link_pattern": r"/en/publications/communication/press-releases/id/pre_\d+",
        "data_category": "monetary_policy",
        "institution": "Swiss National Bank",
        "country": "CH",
        "base_url": "https://www.snb.ch",
    },
    # --- Sweden: Sveriges Riksbank ---
    "se_riksbank_statement": {
        "listing_url": "https://www.riksbank.se/en-gb/monetary-policy/the-riksbanks-interest-rate/",
        "rss_feed": "https://www.riksbank.se/en-gb/rss/",
        "link_pattern": r"/en-gb/press-and-published/press-releases/\d{4}/",
        "data_category": "monetary_policy",
        "institution": "Sveriges Riksbank",
        "country": "SE",
        "base_url": "https://www.riksbank.se",
    },
    "se_riksbank_mpr": {
        # Monetary Policy Report
        "listing_url": "https://www.riksbank.se/en-gb/monetary-policy/monetary-policy-report/",
        "rss_feed": "https://www.riksbank.se/en-gb/rss/",
        "link_pattern": r"/en-gb/monetary-policy/monetary-policy-report/\d{4}/",
        "data_category": "monetary_policy",
        "institution": "Sveriges Riksbank",
        "country": "SE",
        "base_url": "https://www.riksbank.se",
    },
}

_CONTENT_SELECTORS = [
    "div.page-content",
    "div.release-content",
    "div#main-content",
    "article",
    "main",
]

_DATE_PATTERNS = [
    r"\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}",
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}",
    r"\d{4}-\d{2}-\d{2}",
]


class OtherCBFetcher(BaseFetcher):
    """Generic central bank fetcher used by RBA, BOC, SNB, and Riksbank."""

    @property
    def institution(self) -> str:  # type: ignore[override]
        return _SOURCE_CONFIG.get(self.source_id, {}).get("institution", "Central Bank")

    @property
    def country(self) -> str:  # type: ignore[override]
        return _SOURCE_CONFIG.get(self.source_id, {}).get("country", "")

    language = "en"

    async def fetch_latest(self) -> list[FetchResult]:
        cfg = _SOURCE_CONFIG.get(self.source_id)
        if not cfg:
            raise ValueError(f"No config for {self.source_id}")

        html = await self._get_html(cfg["listing_url"])
        soup = BeautifulSoup(html, "html.parser")
        pattern = cfg.get("link_pattern", "")
        base_url = cfg.get("base_url", "")

        for a in soup.find_all("a", href=True):
            if pattern and re.search(pattern, a["href"]):
                url = self._resolve_url(a["href"], base_url)
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
