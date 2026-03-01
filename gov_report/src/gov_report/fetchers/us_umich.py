"""University of Michigan fetcher — Consumer Sentiment."""

from __future__ import annotations

from bs4 import BeautifulSoup

from gov_report.fetchers.base import BaseFetcher
from gov_report.models import FetchResult

_LISTING_URL = "http://www.sca.isr.umich.edu/"

_CONTENT_SELECTORS = [
    "article",
    ".field-item",
    "#content",
    ".main-content",
]

_DATE_PATTERNS = [
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}",
    r"\d{4}-\d{2}-\d{2}",
]


class UMichFetcher(BaseFetcher):
    institution = "University of Michigan"
    country = "US"
    language = "en"

    async def fetch_latest(self) -> list[FetchResult]:
        html = await self._get_html(_LISTING_URL)
        soup = BeautifulSoup(html, "html.parser")

        # Look for the latest survey press release link
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True).lower()
            if "survey" in text or "sentiment" in text or "consumer" in text:
                url = a["href"]
                if not url.startswith("http"):
                    url = "http://www.sca.isr.umich.edu/" + url.lstrip("/")
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
        return self._make_result(
            url=url,
            title=title,
            publish_date=pub_date,
            content_html=content,
            data_category="consumer_sentiment",
        )

    def _extract_title(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for sel in ["h1", "h2", "title"]:
            el = soup.select_one(sel)
            if el and el.get_text(strip=True):
                return el.get_text(strip=True)
        return "Consumer Sentiment Survey"
