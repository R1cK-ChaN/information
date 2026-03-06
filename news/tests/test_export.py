"""Tests for news -> doc_parser export adapter."""

import hashlib
import json

import pytest

from src.common.export import (
    _news_sha256,
    convert_item,
    convert_item_llm,
    save_extraction,
    has_extraction,
)


def _sample_item(**overrides) -> dict:
    """Create a minimal news item dict for testing."""
    base = {
        "item_id": hashlib.sha256(b"https://example.com/article").hexdigest()[:16],
        "source": "CNBC",
        "title": "Fed Holds Rates Steady",
        "link": "https://example.com/article",
        "published": "2025-06-15T12:00:00+00:00",
        "fetched_at": "2025-06-15T12:05:00+00:00",
        "feed_category": "centralbanks",
        "impact_level": "high",
        "finance_category": "monetary_policy",
        "confidence": 0.85,
        "summary": "The Federal Reserve kept rates unchanged at its June meeting.",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# SHA-256 matching
# ---------------------------------------------------------------------------

class TestNewsSha256:
    def test_first_16_chars_match_item_id(self):
        link = "https://example.com/article"
        sha = _news_sha256(link)
        item_id = hashlib.sha256(link.encode()).hexdigest()[:16]
        assert sha[:16] == item_id

    def test_full_64_chars(self):
        sha = _news_sha256("https://example.com/article")
        assert len(sha) == 64


# ---------------------------------------------------------------------------
# convert_item
# ---------------------------------------------------------------------------

class TestConvertItem:
    def test_all_fields_present(self):
        result = convert_item(_sample_item())
        expected_keys = {
            "sha256", "file_name", "source", "local_path", "mime_type",
            "file_size_bytes", "processed_at",
            "title", "institution", "authors", "publish_date", "data_period",
            "country", "market", "asset_class", "sector", "document_type",
            "event_type", "subject", "subject_id", "language",
            "contains_commentary", "impact_level", "confidence",
            "markdown", "parse_info", "extraction_info",
        }
        assert set(result.keys()) == expected_keys

    def test_field_values(self):
        item = _sample_item()
        result = convert_item(item)
        assert result["title"] == "Fed Holds Rates Steady"
        assert result["institution"] == "CNBC"
        assert result["publish_date"] == "2025-06-15"
        assert result["document_type"] == "News Article"
        assert result["source"] == "news"
        assert result["mime_type"] == "text/html"
        assert result["language"] == "en"

    def test_market_lookup(self):
        result = convert_item(_sample_item(feed_category="centralbanks"))
        assert result["market"] == "Global Markets"

    def test_asset_class_lookup(self):
        result = convert_item(_sample_item(finance_category="monetary_policy"))
        assert result["asset_class"] == "Macro"

    def test_event_type_lookup(self):
        result = convert_item(_sample_item(finance_category="monetary_policy"))
        assert result["event_type"] == "Policy Statement"

    def test_with_summary(self):
        result = convert_item(_sample_item(summary="A summary."))
        assert result["contains_commentary"] is True
        assert "## Summary" in result["markdown"]
        assert "A summary." in result["markdown"]

    def test_without_summary(self):
        result = convert_item(_sample_item(summary=None))
        assert result["contains_commentary"] is False
        assert "## Summary" not in result["markdown"]

    def test_impact_level_and_confidence_preserved(self):
        result = convert_item(_sample_item(impact_level="critical", confidence=0.92))
        assert result["impact_level"] == "critical"
        assert result["confidence"] == 0.92

    def test_parse_info_static(self):
        result = convert_item(_sample_item())
        pi = result["parse_info"]
        assert pi["parse_mode"] == "news_feed"
        assert pi["page_count"] == 0

    def test_extraction_info_static(self):
        result = convert_item(_sample_item())
        ei = result["extraction_info"]
        assert ei["provider"] == "news_classifier"
        assert ei["llm_model"] is None


# ---------------------------------------------------------------------------
# save / has extraction
# ---------------------------------------------------------------------------

class TestSaveExtraction:
    def test_creates_bucketed_path(self, tmp_path):
        result = convert_item(_sample_item())
        path = save_extraction(result, tmp_path)
        sha = result["sha256"]
        assert path == tmp_path / sha[:4] / f"{sha}.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["title"] == "Fed Holds Rates Steady"

    def test_has_extraction_true(self, tmp_path):
        result = convert_item(_sample_item())
        save_extraction(result, tmp_path)
        assert has_extraction(result["sha256"], tmp_path) is True

    def test_has_extraction_false(self, tmp_path):
        assert has_extraction("0" * 64, tmp_path) is False


# ---------------------------------------------------------------------------
# convert_item_llm
# ---------------------------------------------------------------------------

class TestConvertItemLLM:
    _LLM_FIELDS = {
        "title": "Fed Holds Rates Steady at June Meeting",
        "institution": "Federal Reserve",
        "authors": "J. Powell",
        "publish_date": "2025-06-15",
        "data_period": None,
        "country": "US",
        "market": "US Treasuries",
        "asset_class": "Fixed Income",
        "sector": "Interest Rate",
        "document_type": "Policy Statement",
        "event_type": "Policy Statement",
        "subject": "Federal Funds Rate",
        "subject_id": "FEDFUNDS",
        "language": "en",
        "contains_commentary": True,
        "impact_level": "high",
        "confidence": 0.9,
    }

    def test_all_fields_present(self):
        result = convert_item_llm(_sample_item(), self._LLM_FIELDS, "openai/gpt-4o-mini", 500)
        expected_keys = {
            "sha256", "file_name", "source", "local_path", "mime_type",
            "file_size_bytes", "processed_at",
            "title", "institution", "authors", "publish_date", "data_period",
            "country", "market", "asset_class", "sector", "document_type",
            "event_type", "subject", "subject_id", "language",
            "contains_commentary", "impact_level", "confidence",
            "markdown", "parse_info", "extraction_info",
        }
        assert set(result.keys()) == expected_keys

    def test_uses_llm_fields(self):
        result = convert_item_llm(_sample_item(), self._LLM_FIELDS, "openai/gpt-4o-mini", 500)
        assert result["title"] == "Fed Holds Rates Steady at June Meeting"
        assert result["institution"] == "Federal Reserve"
        assert result["authors"] == "J. Powell"
        assert result["country"] == "US"
        assert result["market"] == "US Treasuries"
        assert result["asset_class"] == "Fixed Income"
        assert result["impact_level"] == "high"
        assert result["confidence"] == 0.9

    def test_extraction_info_provider_llm(self):
        result = convert_item_llm(_sample_item(), self._LLM_FIELDS, "openai/gpt-4o-mini", 500)
        ei = result["extraction_info"]
        assert ei["provider"] == "llm"
        assert ei["llm_model"] == "openai/gpt-4o-mini"
        assert ei["duration_ms"] == 500

    def test_fallback_to_item_metadata(self):
        """Empty LLM fields should fall back to item metadata."""
        result = convert_item_llm(_sample_item(), {}, "openai/gpt-4o-mini", 100)
        assert result["title"] == "Fed Holds Rates Steady"  # from item
        assert result["institution"] == "CNBC"  # from item["source"]
        assert result["impact_level"] == "info"  # default fallback
        assert result["language"] == "en"  # default

    def test_confidence_coerced_to_float(self):
        fields = {"confidence": "0.85"}
        result = convert_item_llm(_sample_item(), fields, "openai/gpt-4o-mini", 100)
        assert result["confidence"] == 0.85

    def test_contains_commentary_string_true(self):
        fields = {"contains_commentary": "true"}
        result = convert_item_llm(_sample_item(), fields, "openai/gpt-4o-mini", 100)
        assert result["contains_commentary"] is True

    def test_contains_commentary_string_false(self):
        fields = {"contains_commentary": "false"}
        result = convert_item_llm(_sample_item(), fields, "openai/gpt-4o-mini", 100)
        assert result["contains_commentary"] is False


