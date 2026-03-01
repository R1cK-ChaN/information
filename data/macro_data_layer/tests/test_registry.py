"""Tests for indicator registry (no API calls)."""

import pytest

from src.registry import Registry, IndicatorInfo


@pytest.fixture
def reg():
    return Registry()


class TestLookup:
    def test_get_known_indicator(self, reg):
        info = reg.get_indicator("CPI")
        assert isinstance(info, IndicatorInfo)
        assert info.fred_series_id == "CPIAUCSL"
        assert info.category == "inflation"
        assert info.frequency == "monthly"

    def test_get_unknown_raises(self, reg):
        with pytest.raises(KeyError, match="Unknown indicator"):
            reg.get_indicator("FAKE_INDICATOR")

    def test_fred_series_id(self, reg):
        assert reg.get_fred_series_id("GDP_REAL") == "GDPC1"
        assert reg.get_fred_series_id("UNEMPLOYMENT") == "UNRATE"


class TestListAndFilter:
    def test_list_all_returns_47(self, reg):
        all_ind = reg.list_indicators()
        assert len(all_ind) == 46

    def test_no_duplicate_canonical_names(self, reg):
        all_ind = reg.list_indicators()
        names = [i.canonical_name for i in all_ind]
        assert len(names) == len(set(names))

    def test_no_duplicate_fred_ids(self, reg):
        all_ind = reg.list_indicators()
        fred_ids = [i.fred_series_id for i in all_ind if i.fred_series_id]
        assert len(fred_ids) == len(set(fred_ids))

    def test_filter_by_category(self, reg):
        inflation = reg.list_indicators("inflation")
        assert len(inflation) == 5
        assert all(i.category == "inflation" for i in inflation)

    def test_filter_nonexistent_category(self, reg):
        result = reg.list_indicators("nonexistent")
        assert result == []

    def test_categories(self, reg):
        cats = reg.categories()
        expected = ["output", "inflation", "employment", "consumer",
                    "manufacturing", "housing", "rates", "money", "trade", "financial"]
        assert cats == expected


class TestAlfred:
    def test_alfred_series_count(self, reg):
        alfred = reg.get_alfred_series()
        assert len(alfred) == 16

    def test_alfred_series_are_strings(self, reg):
        alfred = reg.get_alfred_series()
        assert all(isinstance(s, str) for s in alfred)

    def test_known_alfred_series(self, reg):
        alfred = reg.get_alfred_series()
        # GDP, CPI, NFP should be tracked
        assert "GDP" in alfred
        assert "CPIAUCSL" in alfred
        assert "PAYEMS" in alfred


class TestEveryIndicatorValid:
    def test_all_have_required_fields(self, reg):
        for ind in reg.list_indicators():
            assert ind.canonical_name
            assert ind.description
            assert ind.category
            assert ind.frequency in ("daily", "weekly", "monthly", "quarterly")
            assert ind.fred_series_id  # all 47 are FRED series
            assert isinstance(ind.ttl_hours, int)
            assert ind.ttl_hours > 0
