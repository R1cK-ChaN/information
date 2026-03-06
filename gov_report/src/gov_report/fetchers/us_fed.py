"""Fed fetcher — speeches, press releases, testimony, FOMC, Beige Book, IP."""

from __future__ import annotations

import re

import feedparser
from bs4 import BeautifulSoup

from gov_report.fetchers.base import BaseFetcher
from gov_report.models import FetchResult

# Listing pages and URL patterns
_SOURCE_CONFIG = {
    # RSS-backed sources – fetch latest entry from the feed then scrape its URL
    "us_fed_speeches": {
        "listing_url": "https://www.federalreserve.gov/feeds/speeches.xml",
        "is_rss": True,
        "data_category": "speeches",
    },
    "us_fed_press_all": {
        "listing_url": "https://www.federalreserve.gov/feeds/press_all.xml",
        "is_rss": True,
        "data_category": "press_releases",
    },
    "us_fed_testimony": {
        "listing_url": "https://www.federalreserve.gov/feeds/testimony.xml",
        "is_rss": True,
        "data_category": "testimony",
    },
    "us_fed_fomc_statement": {
        "listing_url": "https://www.federalreserve.gov/newsevents/pressreleases.htm",
        "link_pattern": r"/newsevents/pressreleases/monetary\d{8}a\.htm",
        "data_category": "monetary_policy",
    },
    "us_fed_fomc_minutes": {
        "listing_url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
        "link_pattern": r"/monetarypolicy/fomcminutes\d{8}\.htm",
        "data_category": "monetary_policy",
    },
    "us_fed_beigebook": {
        "listing_url": "https://www.federalreserve.gov/monetarypolicy/beige-book-default.htm",
        "link_pattern": r"/monetarypolicy/beigebook\d{6}\.htm",
        "data_category": "economic_conditions",
    },
    "us_fed_ip": {
        "listing_url": "https://www.federalreserve.gov/releases/g17/current/",
        "link_pattern": None,  # direct page
        "data_category": "industrial_production",
    },
}

_CONTENT_SELECTORS = ["#content", "article", "div.col-xs-12", "#article"]

_DATE_PATTERNS = [
    r"(?:Released|Issued|Date):\s*\w+\s+\d{1,2},?\s+\d{4}",
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}",
    r"\d{4}-\d{2}-\d{2}",
]


class FedFetcher(BaseFetcher):
    institution = "Federal Reserve"
    country = "US"
    language = "en"

    async def fetch_latest(self) -> list[FetchResult]:
        cfg = _SOURCE_CONFIG.get(self.source_id)
        if not cfg:
            raise ValueError(f"No config for {self.source_id}")

        if cfg.get("is_rss"):
            feed = feedparser.parse(cfg["listing_url"])
            if feed.entries:
                url = feed.entries[0].get("link", "")
                if url:
                    return [await self.fetch_by_url(url)]
            return []

        if self.source_id == "us_fed_ip":
            # Industrial production is a direct page
            return [await self.fetch_by_url(cfg["listing_url"])]

        # For others, scrape the listing page for the latest link
        html = await self._get_html(cfg["listing_url"])
        soup = BeautifulSoup(html, "html.parser")
        pattern = cfg["link_pattern"]

        for a in soup.find_all("a", href=True):
            if re.search(pattern, a["href"]):
                url = a["href"]
                if not url.startswith("http"):
                    url = "https://www.federalreserve.gov" + url
                return [await self.fetch_by_url(url)]

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
