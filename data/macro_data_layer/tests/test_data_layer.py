"""End-to-end tests for MacroDataLayer (uses real FRED API key)."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from dotenv import load_dotenv

load_dotenv()

from src.data_layer import MacroDataLayer

API_KEY = os.getenv("FRED_API_KEY")

pytestmark = pytest.mark.skipif(not API_KEY, reason="FRED_API_KEY not set")


@pytest.fixture(scope="module")
def dl(tmp_path_factory):
    """MacroDataLayer with a temp DB so tests don't pollute production data."""
    tmp_dir = tmp_path_factory.mktemp("macro_test")
    db_path = str(tmp_dir / "test_macro.db")

    # Patch the config to use temp DB
    config_path = Path(__file__).resolve().parent.parent / "config" / "data_layer.yaml"
    import yaml
    with open(config_path) as f:
        config = yaml.safe_load(f)
    config["storage"]["sqlite_path"] = db_path

    tmp_config = tmp_dir / "test_config.yaml"
    with open(tmp_config, "w") as f:
        yaml.dump(config, f)

    layer = MacroDataLayer(config_path=tmp_config)
    yield layer
    layer.close()


class TestGet:
    def test_get_cpi(self, dl):
        """First call triggers lazy refresh from FRED, returns data."""
        df = dl.get("CPI", "US")
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 100
        assert set(df.columns) >= {"date", "value", "source", "series_id"}

    def test_get_with_date_range(self, dl):
        """Filtered query after data is already loaded."""
        df = dl.get("CPI", "US", start="2024-01-01", end="2024-06-01")
        assert len(df) > 0
        assert df["date"].min() >= pd.Timestamp("2024-01-01")
        assert df["date"].max() <= pd.Timestamp("2024-06-01")

    def test_second_get_uses_cache(self, dl):
        """Second call should serve from local DB (not stale yet)."""
        # First call loads data
        dl.get("UNEMPLOYMENT", "US")
        # Second call should not trigger a refresh
        sync_before = dl.storage.get_sync_info("UNEMPLOYMENT:US")
        df = dl.get("UNEMPLOYMENT", "US")
        sync_after = dl.storage.get_sync_info("UNEMPLOYMENT:US")
        # refresh_count should not have increased
        assert sync_after["refresh_count"] == sync_before["refresh_count"]
        assert len(df) > 0


class TestVintage:
    def test_get_vintage_requires_alfred_tracked(self, dl):
        """Non-ALFRED indicator should raise ValueError."""
        with pytest.raises(ValueError, match="not tracked"):
            dl.get_vintage("INITIAL_CLAIMS", "US")

    def test_get_vintage_empty_before_bootstrap(self, dl):
        """Vintage query returns empty if ALFRED data not bootstrapped."""
        df = dl.get_vintage("GDP_REAL", "US", as_of="2024-06-30")
        # May be empty since we haven't bootstrapped ALFRED data
        assert isinstance(df, pd.DataFrame)


class TestListAndDescribe:
    def test_list_indicators(self, dl):
        df = dl.list_indicators()
        assert len(df) == 46
        assert "name" in df.columns
        assert "category" in df.columns

    def test_list_by_category(self, dl):
        df = dl.list_indicators("rates")
        assert len(df) > 0
        assert all(df["category"] == "rates")

    def test_describe(self, dl):
        desc = dl.describe("CPI")
        assert desc["canonical_name"] == "CPI"
        assert desc["fred_series_id"] == "CPIAUCSL"
        assert desc["frequency"] == "monthly"


class TestUnits:
    def test_get_with_pch(self, dl):
        """units='pch' returns percent change, not raw levels."""
        raw = dl.get("CPI", "US", start="2024-01-01", end="2024-06-01")
        pch = dl.get("CPI", "US", start="2024-01-01", end="2024-06-01", units="pch")
        assert len(pch) > 0
        # Raw CPI is ~300+, percent change should be small (< 5)
        assert raw["value"].mean() > 100
        assert abs(pch["value"].mean()) < 5

    def test_get_with_pc1(self, dl):
        """units='pc1' returns year-over-year percent change."""
        pc1 = dl.get("CPI", "US", start="2024-01-01", end="2024-06-01", units="pc1")
        assert len(pc1) > 0
        # YoY CPI inflation should be in a reasonable range
        assert all(abs(pc1["value"]) < 20)

    def test_get_with_log(self, dl):
        """units='log' returns natural log of the series."""
        raw = dl.get("CPI", "US", start="2024-01-01", end="2024-06-01")
        log = dl.get("CPI", "US", start="2024-01-01", end="2024-06-01", units="log")
        assert len(log) > 0
        # log(300) ~ 5.7
        assert log["value"].mean() < 10


class TestRefresh:
    def test_refresh_single(self, dl):
        result = dl.refresh("CPI", "US")
        assert isinstance(result, dict)
        assert "refreshed" in result
        assert "failed" in result

    def test_refresh_uses_lookback(self, dl):
        """Refresh re-fetches a lookback window, not just new dates."""
        # Load a monthly series
        dl.get("NFP", "US")
        sync_before = dl.storage.get_sync_info("NFP:US")

        # Force staleness by manipulating last_refresh
        dl.storage.conn.execute(
            "UPDATE sync_log SET last_refresh = '2000-01-01T00:00:00+00:00' WHERE series_key = 'NFP:US'"
        )
        dl.storage.conn.commit()

        # Refresh — should re-fetch with 90-day lookback (monthly), not just new dates
        dl._refresh_series("NFP", "US")
        sync_after = dl.storage.get_sync_info("NFP:US")
        assert sync_after["refresh_count"] > sync_before["refresh_count"]
