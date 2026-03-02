"""China Ministry of Finance fetcher — fiscal revenue/expenditure, bond issuance."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from gov_report.fetchers.base import BaseFetcher
from gov_report.models import FetchResult

_MOF_BASE = "https://www.mof.gov.cn"

_SOURCE_CONFIG = {
    "cn_mof_fiscal": {
        "listing_url": f"{_MOF_BASE}/zhengwuxinxi/caizhengshuju/",
        "keywords": ["财政收入", "财政支出", "财政数据", "一般公共预算"],
        "data_category": "fiscal_policy",
    },
    "cn_mof_bond": {
        "listing_url": f"{_MOF_BASE}/zhengwuxinxi/zhengfuzhaiquan/",
        "keywords": ["国债", "地方政府债", "债券", "发行"],
        "data_category": "bond_issuance",
    },
}

_CONTENT_SELECTORS = [
    "div.TRS_Editor",
    "div#zoom",
    "div.article-content",
    "div.content",
    "article",
]

_DATE_PATTERNS = [
    r"\d{4}年\d{1,2}月\d{1,2}日",
    r"\d{4}-\d{2}-\d{2}",
    r"\d{4}/\d{2}/\d{2}",
]


class MOFFetcher(BaseFetcher):
    institution = "中国财政部"
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
        for sel in ["h1", "h2", "title"]:
            el = soup.select_one(sel)
            if el and el.get_text(strip=True):
                return el.get_text(strip=True)
        return self.source_id

    def _extract_cn_date(self, html: str) -> str | None:
        soup = BeautifulSoup(html, "html.parser")
        meta = soup.find("meta", attrs={"name": "PubDate"})
        if meta and meta.get("content"):
            return self._normalize_date(meta["content"])
        m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", html)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        return self._extract_date(html, _DATE_PATTERNS)
