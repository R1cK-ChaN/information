"""NBS (国家统计局) fetcher — CPI, PPI, GDP, PMI, Industrial, Retail, FAI."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from gov_report.fetchers.base import BaseFetcher
from gov_report.models import FetchResult

_SOURCE_CONFIG = {
    "cn_stats_cpi": {
        "listing_url": "https://www.stats.gov.cn/sj/zxfb/",
        "keywords": ["居民消费价格", "CPI"],
        "data_category": "inflation",
    },
    "cn_stats_ppi": {
        "listing_url": "https://www.stats.gov.cn/sj/zxfb/",
        "keywords": ["工业生产者出厂价格", "PPI"],
        "data_category": "inflation",
    },
    "cn_stats_gdp": {
        "listing_url": "https://www.stats.gov.cn/sj/zxfb/",
        "keywords": ["国内生产总值", "GDP", "国民经济"],
        "data_category": "gdp",
    },
    "cn_stats_pmi": {
        "listing_url": "https://www.stats.gov.cn/sj/zxfb/",
        "keywords": ["采购经理指数", "PMI"],
        "data_category": "manufacturing",
    },
    "cn_stats_industrial": {
        "listing_url": "https://www.stats.gov.cn/sj/zxfb/",
        "keywords": ["规模以上工业增加值", "工业增加值"],
        "data_category": "industrial_production",
    },
    "cn_stats_retail": {
        "listing_url": "https://www.stats.gov.cn/sj/zxfb/",
        "keywords": ["社会消费品零售总额", "消费品零售"],
        "data_category": "consumption",
    },
    "cn_stats_fai": {
        "listing_url": "https://www.stats.gov.cn/sj/zxfb/",
        "keywords": ["固定资产投资", "投资"],
        "data_category": "investment",
    },
}

_CONTENT_SELECTORS = [
    "div.TRS_Editor",
    "div#zoom",
    "div.center_xilan",
    "div.xilan_con",
    "article",
]

_DATE_PATTERNS = [
    r"\d{4}年\d{1,2}月\d{1,2}日",
    r"\d{4}-\d{2}-\d{2}",
    r"\d{4}/\d{2}/\d{2}",
]

_BASE_URL = "https://www.stats.gov.cn"


class NBSFetcher(BaseFetcher):
    institution = "国家统计局"
    country = "CN"
    language = "zh"

    async def fetch_latest(self) -> list[FetchResult]:
        cfg = _SOURCE_CONFIG.get(self.source_id)
        if not cfg:
            raise ValueError(f"No config for {self.source_id}")

        html = await self._get_html(cfg["listing_url"], encoding="utf-8")
        soup = BeautifulSoup(html, "html.parser")
        keywords = cfg["keywords"]

        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True)
            if any(kw in text for kw in keywords):
                url = self._resolve_url(a["href"], cfg["listing_url"])
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
        for sel in ["h1", "div.xilan_tit", "h2", "title"]:
            el = soup.select_one(sel)
            if el and el.get_text(strip=True):
                return el.get_text(strip=True)
        return self.source_id

    def _extract_cn_date(self, html: str) -> str | None:
        """Extract publication date, trying meta tag first."""
        soup = BeautifulSoup(html, "html.parser")
        # 1. <meta name="PubDate" content="2026/02/11 09:30">
        meta = soup.find("meta", attrs={"name": "PubDate"})
        if meta and meta.get("content"):
            return self._normalize_date(meta["content"])
        # 2. Chinese format: 2026年2月11日
        m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", html)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        return self._extract_date(html, _DATE_PATTERNS)
