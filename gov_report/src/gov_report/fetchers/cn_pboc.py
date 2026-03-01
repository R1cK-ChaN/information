"""PBOC (中国人民银行) fetcher — Monetary data, LPR, Monetary Policy Report."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from gov_report.fetchers.base import BaseFetcher
from gov_report.models import FetchResult

_SOURCE_CONFIG = {
    "cn_pboc_monetary": {
        "listing_url": "http://www.pbc.gov.cn/diaochatongjisi/116219/116319/index.html",
        "keywords": ["社会融资规模", "M2", "货币供应量", "金融统计"],
        "data_category": "monetary",
    },
    "cn_pboc_lpr": {
        "listing_url": "http://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125440/index.html",
        "keywords": ["贷款市场报价利率", "LPR"],
        "data_category": "interest_rate",
    },
    "cn_pboc_mpr": {
        "listing_url": "http://www.pbc.gov.cn/zhengcehuobisi/125207/125227/125957/index.html",
        "keywords": ["货币政策执行报告", "货币政策报告"],
        "data_category": "monetary_policy",
        "is_pdf": True,
    },
}

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

_BASE_URL = "http://www.pbc.gov.cn"


class PBOCFetcher(BaseFetcher):
    institution = "中国人民银行"
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

                if cfg.get("is_pdf") and url.endswith(".pdf"):
                    return [await self._fetch_pdf(url, cfg)]

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

    async def _fetch_pdf(self, url: str, cfg: dict) -> FetchResult:
        pdf_bytes = await self._get_bytes(url)
        return self._make_result(
            url=url,
            title=cfg.get("keywords", [self.source_id])[0],
            publish_date="",
            content_html="",
            content_type="pdf",
            pdf_bytes=pdf_bytes,
            data_category=cfg.get("data_category", ""),
        )

    def _extract_title(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for sel in ["h1", "div.tit", "h2", "title"]:
            el = soup.select_one(sel)
            if el and el.get_text(strip=True):
                return el.get_text(strip=True)
        return self.source_id

    def _extract_cn_date(self, html: str) -> str | None:
        m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", html)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        return self._extract_date(html, _DATE_PATTERNS)
