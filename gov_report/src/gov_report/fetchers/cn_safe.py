"""SAFE (国家外汇管理局) fetcher — FX Reserves."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from gov_report.fetchers.base import BaseFetcher
from gov_report.models import FetchResult

_LISTING_URL = "https://www.safe.gov.cn/safe/whcbzb/index.html"

_CONTENT_SELECTORS = [
    "div.TRS_Editor",
    "div#zoom",
    "div.content",
    "article",
]

_DATE_PATTERNS = [
    r"\d{4}年\d{1,2}月\d{1,2}日",
    r"\d{4}-\d{2}-\d{2}",
]

_BASE_URL = "https://www.safe.gov.cn"


class SAFEFetcher(BaseFetcher):
    institution = "国家外汇管理局"
    country = "CN"
    language = "zh"

    async def fetch_latest(self) -> list[FetchResult]:
        html = await self._get_html(_LISTING_URL, encoding="utf-8")
        soup = BeautifulSoup(html, "html.parser")

        keywords = ["外汇储备", "储备规模"]
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True)
            if any(kw in text for kw in keywords):
                url = self._resolve_url(a["href"], _LISTING_URL)
                try:
                    return [await self.fetch_by_url(url)]
                except Exception:
                    continue
        return []

    async def fetch_by_url(self, url: str) -> FetchResult:
        html = await self._get_html(url, encoding="utf-8")
        content = self._extract_content(html, _CONTENT_SELECTORS)
        title = self._extract_title(html)
        pub_date = self._extract_cn_date(html) or ""
        return self._make_result(
            url=url,
            title=title,
            publish_date=pub_date,
            content_html=content,
            data_category="fx_reserves",
        )

    def _extract_title(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for sel in ["h1", "h2", "title"]:
            el = soup.select_one(sel)
            if el and el.get_text(strip=True):
                return el.get_text(strip=True)
        return self.source_id

    def _extract_cn_date(self, html: str) -> str | None:
        m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", html)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        return self._extract_date(html, _DATE_PATTERNS)
