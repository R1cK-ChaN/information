"""Data models for gov_report."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class FetchResult:
    """Result of fetching a single government report page."""

    url: str
    title: str
    publish_date: str  # ISO date (YYYY-MM-DD)
    content_html: str  # extracted content div HTML
    content_type: Literal["html", "pdf"] = "html"
    source_id: str = ""  # e.g. "us_bls_cpi"
    institution: str = ""  # e.g. "BLS"
    country: str = ""  # "US" | "CN"
    language: str = ""  # "en" | "zh"
    data_category: str = ""  # "inflation" | "employment" | etc.
    pdf_bytes: bytes | None = None
    metadata: dict = field(default_factory=dict)
