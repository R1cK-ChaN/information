"""Tests for pipeline integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from gov_report.hasher import content_sha
from gov_report.models import FetchResult
from gov_report.pipeline import process_report


@pytest.fixture
def sample_fetch_result():
    return FetchResult(
        url="https://www.bls.gov/news.release/cpi.htm",
        title="Consumer Price Index - January 2025",
        publish_date="2025-02-12",
        content_html="<h1>CPI Report</h1><p>The CPI rose 0.3% in January.</p>",
        source_id="us_bls_cpi",
        institution="BLS",
        country="US",
        language="en",
        data_category="inflation",
    )


def test_content_sha_matches(sample_fetch_result):
    """Verify sha computation is consistent."""
    sha = content_sha(sample_fetch_result.url, sample_fetch_result.publish_date)
    assert len(sha) == 64


@pytest.mark.asyncio
async def test_process_report_dedup(tmp_settings, sample_fetch_result):
    """Verify that duplicate reports are skipped."""
    from doc_parser.textin_client import ExtractionResult

    tmp_settings.ensure_dirs()

    mock_result = ExtractionResult(
        fields={
            "title": "CPI Report",
            "institution": "BLS",
            "country": "US",
            "language": "en",
        },
        duration_ms=100,
    )

    with patch(
        "gov_report.pipeline.run_extraction",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        # First call should process
        result1 = await process_report(tmp_settings, sample_fetch_result)
        assert result1 is not None
        assert result1["sha256"] == content_sha(
            sample_fetch_result.url, sample_fetch_result.publish_date
        )

        # Second call should skip (dedup)
        result2 = await process_report(tmp_settings, sample_fetch_result)
        assert result2 is None


@pytest.mark.asyncio
async def test_process_report_schema(tmp_settings, sample_fetch_result):
    """Verify output JSON has the same schema as doc_parser."""
    from doc_parser.textin_client import ExtractionResult

    tmp_settings.ensure_dirs()

    mock_result = ExtractionResult(
        fields={
            "title": "Consumer Price Index",
            "institution": "BLS",
            "publish_date": "2025-02-12",
            "country": "US",
            "language": "en",
            "impact_level": "high",
            "confidence": 0.85,
        },
        duration_ms=150,
    )

    with patch(
        "gov_report.pipeline.run_extraction",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        result = await process_report(tmp_settings, sample_fetch_result)

    assert result is not None
    # Check all required top-level keys match doc_parser schema
    required_keys = [
        "sha256", "file_name", "source", "processed_at",
        "title", "institution", "authors", "publish_date", "data_period",
        "country", "market", "asset_class", "sector",
        "document_type", "event_type", "subject", "subject_id",
        "language", "contains_commentary", "impact_level", "confidence",
        "markdown", "parse_info", "extraction_info",
    ]
    for key in required_keys:
        assert key in result, f"Missing key: {key}"

    # Verify crawler metadata overrides LLM fields
    assert result["institution"] == "BLS"
    assert result["country"] == "US"
    assert result["language"] == "en"

    # Verify parse_info structure
    assert result["parse_info"]["parse_mode"] == "html_crawl"

    # Verify extraction_info structure
    assert "llm_model" in result["extraction_info"]
    assert "duration_ms" in result["extraction_info"]
