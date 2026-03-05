"""ECB fetcher — press releases, speeches, working papers (via RSS)."""

from __future__ import annotations

import feedparser
from bs4 import BeautifulSoup

from gov_report.fetchers.base import BaseFetcher
from gov_report.models import FetchResult

_SOURCE_CONFIG = {
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
    ".ecb-publicationDate",
    "article",
    ".main-content",
    "#main-wrapper",
    "div.pub-section",
    "div#content",
]

_DATE_PATTERNS = [
    r"\d{1,2}\s+\w+\s+\d{4}",
    r"\d{4}-\d{2}-\d{2}",
]


class ECBFetcher(BaseFetcher):
    institution = "European Central Bank"
    country = "EU"
    language = "en"

    async def fetch_latest(self) -> list[FetchResult]:
        cfg = _SOURCE_CONFIG.get(self.source_id)
        if not cfg:
            raise ValueError(f"No config for {self.source_id}")

        feed = feedparser.parse(cfg["rss_url"])
        if not feed.entries:
            return []

        entry = feed.entries[0]
        url = entry.get("link", "")
        if not url:
            return []

        # Populate title/date from the feed entry when possible, then enrich
        # by fetching the article page itself.
        result = await self.fetch_by_url(url)

        # Prefer the RSS-provided title and date if the scrape didn't find them
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
        for sel in ["h1", "h2", "title"]:
            el = soup.select_one(sel)
            if el and el.get_text(strip=True):
                return el.get_text(strip=True)
        return self.source_id
