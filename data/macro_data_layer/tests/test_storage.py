"""Tests for SQLite storage layer (no API calls)."""

import pandas as pd
import pytest

from src.storage import Storage


@pytest.fixture
def db():
    s = Storage(":memory:")
    yield s
    s.close()


def _make_df(dates, values, source="FRED", series_id="CPIAUCSL"):
    return pd.DataFrame({
        "date": dates,
        "value": values,
        "source": source,
        "series_id": series_id,
    })


class TestMacroSeries:
    def test_upsert_and_read(self, db):
        df = _make_df(["2024-01-01", "2024-02-01"], [300.5, 301.2])
        count = db.upsert_series("CPI:US", df)
        assert count == 2

        result = db.read_series("CPI:US")
        assert len(result) == 2
        assert result.iloc[0]["value"] == 300.5
        assert result.iloc[1]["value"] == 301.2

    def test_upsert_replaces_on_conflict(self, db):
        df1 = _make_df(["2024-01-01"], [300.5])
        db.upsert_series("CPI:US", df1)

        df2 = _make_df(["2024-01-01"], [300.8])  # revised value
        db.upsert_series("CPI:US", df2)

        result = db.read_series("CPI:US")
        assert len(result) == 1
        assert result.iloc[0]["value"] == 300.8

    def test_read_with_date_range(self, db):
        df = _make_df(
            ["2024-01-01", "2024-02-01", "2024-03-01", "2024-04-01"],
            [1.0, 2.0, 3.0, 4.0],
        )
        db.upsert_series("CPI:US", df)

        result = db.read_series("CPI:US", start="2024-02-01", end="2024-03-01")
        assert len(result) == 2
        assert result.iloc[0]["value"] == 2.0
        assert result.iloc[1]["value"] == 3.0

    def test_read_empty_series(self, db):
        result = db.read_series("NONEXISTENT:XX")
        assert len(result) == 0

    def test_get_last_date(self, db):
        assert db.get_last_date("CPI:US") is None

        df = _make_df(["2024-01-01", "2024-06-01", "2024-03-01"], [1.0, 2.0, 3.0])
        db.upsert_series("CPI:US", df)
        assert db.get_last_date("CPI:US") == "2024-06-01"

    def test_null_values(self, db):
        df = _make_df(["2024-01-01", "2024-02-01"], [100.0, float("nan")])
        db.upsert_series("TEST:US", df)

        result = db.read_series("TEST:US")
        assert len(result) == 2
        assert pd.isna(result.iloc[1]["value"])


class TestAlfredVintages:
    def _make_vintages(self):
        return pd.DataFrame({
            "series_id": ["GDPC1"] * 4,
            "date": ["2024-01-01", "2024-01-01", "2024-04-01", "2024-04-01"],
            "realtime_start": ["2024-04-25", "2024-05-30", "2024-07-25", "2024-08-29"],
            "value": [22000.0, 22050.0, 22300.0, 22350.0],
        })

    def test_upsert_and_read_all(self, db):
        df = self._make_vintages()
        count = db.upsert_vintages("GDPC1", df)
        assert count == 4

        result = db.read_all_vintages("GDPC1")
        assert len(result) == 4

    def test_read_vintage_point_in_time(self, db):
        df = self._make_vintages()
        db.upsert_vintages("GDPC1", df)

        # As of 2024-05-01: should see first estimate for Q1, not Q2 yet
        result = db.read_vintage("GDPC1", "2024-05-01")
        assert len(result) == 1
        assert result.iloc[0]["value"] == 22000.0  # first estimate

        # As of 2024-06-01: should see revised Q1
        result = db.read_vintage("GDPC1", "2024-06-01")
        assert len(result) == 1
        assert result.iloc[0]["value"] == 22050.0  # revised

        # As of 2024-09-01: should see both quarters, latest vintages
        result = db.read_vintage("GDPC1", "2024-09-01")
        assert len(result) == 2
        assert result.iloc[0]["value"] == 22050.0  # Q1 revised
        assert result.iloc[1]["value"] == 22350.0  # Q2 revised

    def test_ignore_duplicate_vintages(self, db):
        df = self._make_vintages()
        db.upsert_vintages("GDPC1", df)
        db.upsert_vintages("GDPC1", df)  # same data again

        result = db.read_all_vintages("GDPC1")
        assert len(result) == 4  # no duplicates


class TestSyncLog:
    def test_initial_sync(self, db):
        assert db.get_sync_info("CPI:US") is None

        db.update_sync("CPI:US", "2024-06-01")
        info = db.get_sync_info("CPI:US")
        assert info is not None
        assert info["last_local_date"] == "2024-06-01"
        assert info["refresh_count"] == 1
        assert info["error_count"] == 0

    def test_subsequent_sync(self, db):
        db.update_sync("CPI:US", "2024-06-01")
        db.update_sync("CPI:US", "2024-07-01")

        info = db.get_sync_info("CPI:US")
        assert info["last_local_date"] == "2024-07-01"
        assert info["refresh_count"] == 2

    def test_error_tracking(self, db):
        db.update_sync("CPI:US", "2024-06-01")
        db.update_sync("CPI:US", error=True)

        info = db.get_sync_info("CPI:US")
        assert info["error_count"] == 1
        assert info["last_local_date"] == "2024-06-01"  # unchanged
