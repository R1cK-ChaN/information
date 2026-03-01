"""FRED API integration tests (uses real API key)."""

import os

import pandas as pd
import pytest
from dotenv import load_dotenv

load_dotenv()

from src.providers.fred import FREDProvider

API_KEY = os.getenv("FRED_API_KEY")

pytestmark = pytest.mark.skipif(not API_KEY, reason="FRED_API_KEY not set")


@pytest.fixture(scope="module")
def fred():
    return FREDProvider(API_KEY)


class TestFetchSeries:
    def test_fetch_cpi(self, fred):
        df = fred.fetch_series("CPIAUCSL", start="2024-01-01", end="2024-06-01")
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0
        assert set(df.columns) == {"date", "value", "source", "series_id"}
        assert df["source"].iloc[0] == "FRED"
        assert df["series_id"].iloc[0] == "CPIAUCSL"

    def test_fetch_full_history(self, fred):
        df = fred.fetch_series("UNRATE")
        assert len(df) > 500  # decades of monthly data

    def test_fetch_with_retry(self, fred):
        df = fred.fetch_with_retry(fred.fetch_series, "DGS10", start="2024-01-01", end="2024-03-01")
        assert len(df) > 0


class TestAlfredVintages:
    def test_fetch_gdp_vintages(self, fred):
        df = fred.fetch_all_releases("GDPC1")
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 100
        assert "realtime_start" in df.columns
        assert "date" in df.columns
        assert "value" in df.columns
        assert "series_id" in df.columns

        # Should have multiple vintages per observation date
        per_date = df.groupby("date").size()
        assert per_date.max() > 1  # at least some dates have revisions


class TestSeriesInfo:
    def test_fetch_info(self, fred):
        info = fred.fetch_series_info("CPIAUCSL")
        assert isinstance(info, dict)
        assert "title" in info or "id" in info


class TestUnitsTransform:
    def test_fetch_pch(self, fred):
        """units='pch' returns percent change values."""
        raw = fred.fetch_series("CPIAUCSL", start="2024-01-01", end="2024-06-01")
        pch = fred.fetch_series("CPIAUCSL", start="2024-01-01", end="2024-06-01", units="pch")
        assert len(pch) > 0
        assert len(pch) == len(raw)
        # Raw CPI ~ 300+, pch should be small
        assert raw["value"].mean() > 100
        assert abs(pch["value"].mean()) < 5

    def test_fetch_pc1(self, fred):
        """units='pc1' returns year-over-year percent change."""
        pc1 = fred.fetch_series("UNRATE", start="2024-01-01", end="2024-06-01", units="pc1")
        assert len(pc1) > 0


class TestSupports:
    def test_us_supported(self, fred):
        assert fred.supports("CPI", "US") is True

    def test_non_us_not_supported(self, fred):
        assert fred.supports("CPI", "GB") is False
