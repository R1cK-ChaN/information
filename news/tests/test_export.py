"""Tests for news -> doc_parser export adapter."""

import hashlib
import json

import pytest

from src.export import (
    _news_sha256,
    convert_item,
    save_extraction,
    has_extraction,
    export_items,
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
# export_items
# ---------------------------------------------------------------------------

class TestExportItems:
    def test_basic_export(self, tmp_path):
        items = [_sample_item()]
        stats = export_items(items, tmp_path)
        assert stats == {"exported": 1, "skipped": 0, "total": 1}

    def test_skips_existing(self, tmp_path):
        items = [_sample_item()]
        export_items(items, tmp_path)
        stats = export_items(items, tmp_path)
        assert stats == {"exported": 0, "skipped": 1, "total": 1}

    def test_force_overwrites(self, tmp_path):
        items = [_sample_item()]
        export_items(items, tmp_path)
        stats = export_items(items, tmp_path, force=True)
        assert stats == {"exported": 1, "skipped": 0, "total": 1}

    def test_multiple_items(self, tmp_path):
        items = [
            _sample_item(link="https://example.com/1", item_id="aaa"),
            _sample_item(link="https://example.com/2", item_id="bbb"),
        ]
        stats = export_items(items, tmp_path)
        assert stats["exported"] == 2
        assert stats["total"] == 2
