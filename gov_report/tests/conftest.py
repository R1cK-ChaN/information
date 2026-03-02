"""Shared test fixtures."""

from __future__ import annotations

import pytest

from gov_report.config import Settings


@pytest.fixture
def tmp_settings(tmp_path):
    """Settings pointing to a temp directory."""
    return Settings(
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
        llm_api_key="test-key",
        textin_app_id="test",
        textin_secret_code="test",
    )
