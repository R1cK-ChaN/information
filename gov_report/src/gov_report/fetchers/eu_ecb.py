"""ECB fetcher — rate decisions, accounts, bulletin (HTML) + press, speeches, papers (RSS)."""

from __future__ import annotations

import re

import feedparser
from bs4 import BeautifulSoup

from gov_report.fetchers.base import BaseFetcher
from gov_report.models import FetchResult

_ECB_BASE = "https://www.ecb.europa.eu"

_SOURCE_CONFIG = {
    # HTML-scraping sources
    "eu_ecb_statement": {
        "listing_url": f"{_ECB_BASE}/press/pressreleases/html/index.en.html",
        "link_pattern": r"/press/pr/date/\d{4}/html/.*\.en\.html",
        "rss_feed": "https://www.ecb.europa.eu/rss/press.html",
        "data_category": "monetary_policy",
    },
    "eu_ecb_minutes": {
        # Monetary policy accounts (= minutes equivalent)
        "listing_url": f"{_ECB_BASE}/press/accounts/html/index.en.html",
        "link_pattern": r"/press/accounts/\d{4}/html/.*\.en\.html",
        "rss_feed": "https://www.ecb.europa.eu/rss/press.html",
        "data_category": "monetary_policy",
    },
    "eu_ecb_bulletin": {
        "listing_url": f"{_ECB_BASE}/pub/economic-bulletin/html/index.en.html",
        "link_pattern": r"/pub/economic-bulletin/html/eb\d+\.en\.html",
        "data_category": "economic_conditions",
    },
    # RSS-only sources
    "ecb_press": {
        "rss_url": "https://www.ecb.europa.eu/rss/press.html",
        "data_category": "press_releases",
    },
    "ecb_speeches": {
        "rss_url": "https://www.ecb.europa.eu/rss/speeches.html",
        "data_category": "speeches",
    },
    "ecb_working_papers": {
        "rss_url": "https://www.ecb.europa.eu/rss/wppub.html",
        "data_category": "research",
    },
}

_CONTENT_SELECTORS = [
    "div.ecb-pressContent",
    "article.ecb-publicationPage",
    ".ecb-publicationDate",
    "div.definition",
    "div#main-wrapper",
    ".main-content",
    "main",
    "article",
    "div.pub-section",
    "div#content",
]

_DATE_PATTERNS = [
    r"\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}",
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}",
    r"\d{1,2}\s+\w+\s+\d{4}",
    r"\d{4}-\d{2}-\d{2}",
]


class ECBFetcher(BaseFetcher):
    institution = "ECB"
    country = "EU"
    language = "en"

    async def fetch_latest(self) -> list[FetchResult]:
        cfg = _SOURCE_CONFIG.get(self.source_id)
        if not cfg:
            raise ValueError(f"No config for {self.source_id}")

        # RSS-only sources
        if "rss_url" in cfg and "listing_url" not in cfg:
            return await self._fetch_via_rss(cfg)

        # HTML-scraping sources
        return await self._fetch_via_html(cfg)

    async def _fetch_via_html(self, cfg: dict) -> list[FetchResult]:
        html = await self._get_html(cfg["listing_url"])
        soup = BeautifulSoup(html, "html.parser")
        pattern = cfg.get("link_pattern", "")

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if pattern and re.search(pattern, href):
                url = self._resolve_url(href, _ECB_BASE)
                try:
                    return [await self.fetch_by_url(url)]
                except Exception:
                    continue
        return []

    async def _fetch_via_rss(self, cfg: dict) -> list[FetchResult]:
        feed = feedparser.parse(cfg["rss_url"])
        if not feed.entries:
            return []

        entry = feed.entries[0]
        url = entry.get("link", "")
        if not url:
            return []

        result = await self.fetch_by_url(url)

        if not result.title or result.title == self.source_id:
            result = FetchResult(
                **{
                    **result.__dict__,
                    "title": entry.get("title", self.source_id),
                }
            )
        if not result.publish_date:
            result = FetchResult(
                **{
                    **result.__dict__,
                    "publish_date": entry.get("published", ""),
                }
            )

        return [result]

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
        for sel in ["h1.ecb-pressHeadline", "h1", "h2", "title"]:
            el = soup.select_one(sel)
            if el and el.get_text(strip=True):
                return el.get_text(strip=True)
        return self.source_id
