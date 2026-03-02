"""Export news items to doc_parser extraction format."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Lookup dicts
# ---------------------------------------------------------------------------

_FINANCE_CAT_TO_ASSET_CLASS = {
    "monetary_policy": "Macro",
    "inflation": "Macro",
    "employment": "Macro",
    "rates": "Fixed Income",
    "fx": "FX",
    "commodities": "Commodity",
    "crypto": "Crypto",
    "earnings": "Equity",
    "ipo": "Equity",
    "trade": "Macro",
    "regulation": "Policy",
    "geopolitical_risk": "Macro",
    "general": "Multi-Asset",
}

_FEED_CAT_TO_MARKET = {
    "markets": "Global Markets",
    "forex": "FX",
    "bonds": "US Treasuries",
    "commodities": "Commodities",
    "crypto": "Crypto",
    "centralbanks": "Global Markets",
    "economic": "Macro",
    "ipo": "US Equity",
    "derivatives": "Derivatives",
    "fintech": "Fintech",
    "regulation": "Regulatory",
    "institutional": "Institutional",
    "analysis": "Global Markets",
    "thinktanks": "Geopolitics",
    "government": "Policy",
}

_FINANCE_CAT_TO_EVENT_TYPE = {
    "monetary_policy": "Policy Statement",
    "inflation": "Economic Release",
    "employment": "Economic Release",
    "rates": "Market Move",
    "fx": "Market Move",
    "commodities": "Market Move",
    "crypto": "Market Move",
    "earnings": "Corporate Earnings",
    "ipo": "Corporate Action",
    "trade": "Policy Statement",
    "regulation": "Regulatory Action",
    "geopolitical_risk": "Geopolitical Event",
    "general": "News Article",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _news_sha256(link: str) -> str:
    """Full 64-char SHA-256 of article link (first 16 match item_id)."""
    return hashlib.sha256(link.encode()).hexdigest()


def _compose_markdown(item: dict) -> str:
    """Build a markdown representation of a news item."""
    lines = [
        f"# {item['title']}",
        "",
        f"**Source:** {item['source']}",
        f"**Published:** {item['published']}",
        f"**Category:** {item.get('feed_category', '')}",
        f"**Impact:** {item.get('impact_level', 'info')} (confidence: {item.get('confidence', 0.3)})",
        f"**Link:** {item['link']}",
    ]
    summary = item.get("summary")
    if summary:
        lines += ["", "## Summary", "", summary]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def convert_item(item: dict) -> dict:
    """Convert a news item dict to doc_parser extraction schema."""
    link = item["link"]
    sha = _news_sha256(link)
    finance_cat = item.get("finance_category", "general")
    feed_cat = item.get("feed_category", "")
    summary = item.get("summary")

    return {
        "sha256": sha,
        "file_name": f"news_{item['item_id']}.json",
        "source": "news",
        "local_path": link,
        "mime_type": "text/html",
        "file_size_bytes": 0,
        "processed_at": int(time.time()),

        "title": item["title"],
        "institution": item["source"],
        "authors": None,
        "publish_date": item["published"][:10],
        "data_period": None,
        "country": None,
        "market": _FEED_CAT_TO_MARKET.get(feed_cat),
        "asset_class": _FINANCE_CAT_TO_ASSET_CLASS.get(finance_cat),
        "sector": finance_cat,
        "document_type": "News Article",
        "event_type": _FINANCE_CAT_TO_EVENT_TYPE.get(finance_cat),
        "subject": item["title"],
        "subject_id": None,
        "language": "en",
        "contains_commentary": summary is not None,
        "impact_level": item.get("impact_level", "info"),
        "confidence": item.get("confidence", 0.3),

        "markdown": _compose_markdown(item),

        "parse_info": {
            "page_count": 0,
            "has_chart": False,
            "has_table": False,
            "chart_count": 0,
            "table_count": 0,
            "duration_ms": 0,
            "parse_mode": "news_feed",
        },
        "extraction_info": {
            "provider": "news_classifier",
            "llm_model": None,
            "duration_ms": 0,
        },
    }


def convert_item_llm(
    item: dict,
    extracted_fields: dict,
    llm_model: str,
    duration_ms: int,
) -> dict:
    """Convert a news item using LLM-extracted fields (with fallbacks to item metadata)."""
    link = item["link"]
    sha = _news_sha256(link)
    summary = item.get("summary")

    def _field(key: str, fallback=None):
        v = extracted_fields.get(key)
        return v if v else fallback

    confidence_raw = _field("confidence", 0.3)
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = 0.3

    contains_commentary_raw = _field("contains_commentary", summary is not None)
    if isinstance(contains_commentary_raw, str):
        contains_commentary = contains_commentary_raw.lower() in ("true", "1", "yes")
    else:
        contains_commentary = bool(contains_commentary_raw)

    return {
        "sha256": sha,
        "file_name": f"news_{item['item_id']}.json",
        "source": "news",
        "local_path": link,
        "mime_type": "text/html",
        "file_size_bytes": 0,
        "processed_at": int(time.time()),

        "title": _field("title", item["title"]),
        "institution": _field("institution", item["source"]),
        "authors": _field("authors"),
        "publish_date": _field("publish_date", item["published"][:10]),
        "data_period": _field("data_period"),
        "country": _field("country"),
        "market": _field("market"),
        "asset_class": _field("asset_class"),
        "sector": _field("sector"),
        "document_type": _field("document_type", "News Article"),
        "event_type": _field("event_type"),
        "subject": _field("subject", item["title"]),
        "subject_id": _field("subject_id"),
        "language": _field("language", "en"),
        "contains_commentary": contains_commentary,
        "impact_level": _field("impact_level", "info"),
        "confidence": confidence,

        "markdown": _compose_markdown(item),

        "parse_info": {
            "page_count": 0,
            "has_chart": False,
            "has_table": False,
            "chart_count": 0,
            "table_count": 0,
            "duration_ms": 0,
            "parse_mode": "news_feed",
        },
        "extraction_info": {
            "provider": "llm",
            "llm_model": llm_model,
            "duration_ms": duration_ms,
        },
    }


def save_extraction(result: dict, extraction_path: Path) -> Path:
    """Write a result dict as JSON to the bucketed extraction path."""
    sha = result["sha256"]
    path = extraction_path / sha[:4] / f"{sha}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def has_extraction(sha: str, extraction_path: Path) -> bool:
    """Check whether an extraction JSON already exists for this sha."""
    return (extraction_path / sha[:4] / f"{sha}.json").exists()


