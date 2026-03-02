"""Tests for the shared catalog index."""

import time

import pytest

from widgets.catalog import Catalog


@pytest.fixture
def catalog():
    c = Catalog(":memory:")
    yield c
    c.close()


def _make_result(sha="a" * 64, **overrides):
    base = {
        "sha256": sha,
        "source": "test",
        "title": "Test Report",
        "institution": "Test Corp",
        "publish_date": "2025-06-15",
        "data_period": "Q2 2025",
        "country": "US",
        "market": "Macro",
        "asset_class": "Macro",
        "sector": "Technology",
        "document_type": "Research Report",
        "event_type": None,
        "subject": "Test Subject",
        "subject_id": "TST",
        "language": "en",
        "contains_commentary": True,
        "impact_level": "high",
        "confidence": 0.85,
        "processed_at": int(time.time()),
    }
    base.update(overrides)
    return base


class TestHas:
    def test_has_returns_false_for_missing(self, catalog):
        assert catalog.has("x" * 64) is False

    def test_has_returns_true_after_insert(self, catalog):
        r = _make_result()
        catalog.insert(r, "/tmp/test.json")
        assert catalog.has(r["sha256"]) is True


class TestInsert:
    def test_insert_and_retrieve(self, catalog):
        r = _make_result()
        catalog.insert(r, "/tmp/test.json")
        items = catalog.get_latest(1)
        assert len(items) == 1
        assert items[0]["sha256"] == r["sha256"]
        assert items[0]["title"] == "Test Report"
        assert items[0]["json_path"] == "/tmp/test.json"

    def test_insert_replaces_on_conflict(self, catalog):
        r = _make_result(title="V1")
        catalog.insert(r, "/tmp/v1.json")
        r["title"] = "V2"
        catalog.insert(r, "/tmp/v2.json")
        items = catalog.get_latest(10)
        assert len(items) == 1
        assert items[0]["title"] == "V2"

    def test_contains_commentary_stored_as_int(self, catalog):
        r = _make_result(contains_commentary=True)
        catalog.insert(r, "/tmp/t.json")
        items = catalog.get_latest(1)
        assert items[0]["contains_commentary"] == 1

    def test_missing_fields_default_to_none(self, catalog):
        r = {"sha256": "b" * 64, "processed_at": int(time.time())}
        catalog.insert(r, "/tmp/t.json")
        items = catalog.get_latest(1)
        assert items[0]["title"] is None
        assert items[0]["country"] is None


class TestGetLatest:
    def test_ordered_by_processed_at(self, catalog):
        now = int(time.time())
        catalog.insert(_make_result(sha="a" * 64, processed_at=now - 100), "/a.json")
        catalog.insert(_make_result(sha="b" * 64, processed_at=now), "/b.json")
        items = catalog.get_latest(2)
        assert items[0]["sha256"] == "b" * 64
        assert items[1]["sha256"] == "a" * 64

    def test_filter_by_source(self, catalog):
        catalog.insert(_make_result(sha="a" * 64, source="news"), "/a.json")
        catalog.insert(_make_result(sha="b" * 64, source="gov_report"), "/b.json")
        items = catalog.get_latest(10, source="news")
        assert len(items) == 1
        assert items[0]["source"] == "news"

    def test_filter_by_impact_level(self, catalog):
        catalog.insert(_make_result(sha="a" * 64, impact_level="high"), "/a.json")
        catalog.insert(_make_result(sha="b" * 64, impact_level="low"), "/b.json")
        items = catalog.get_latest(10, impact_level="high")
        assert len(items) == 1
        assert items[0]["impact_level"] == "high"


class TestSearch:
    def test_search_by_title(self, catalog):
        catalog.insert(_make_result(sha="a" * 64, title="Fed raises rates"), "/a.json")
        catalog.insert(_make_result(sha="b" * 64, title="Gold surges"), "/b.json")
        results = catalog.search("raises rates")
        assert len(results) == 1
        assert results[0]["title"] == "Fed raises rates"

    def test_search_no_match(self, catalog):
        catalog.insert(_make_result(title="Unrelated"), "/a.json")
        assert catalog.search("nonexistent") == []


class TestGetRecentTitles:
    def test_returns_recent_titles(self, catalog):
        now = int(time.time())
        catalog.insert(_make_result(sha="a" * 64, title="Recent", processed_at=now), "/a.json")
        catalog.insert(
            _make_result(sha="b" * 64, title="Old", processed_at=now - 100000),
            "/b.json",
        )
        titles = catalog.get_recent_titles(hours=1)
        assert "Recent" in titles
        assert "Old" not in titles

    def test_filter_by_source(self, catalog):
        now = int(time.time())
        catalog.insert(_make_result(sha="a" * 64, source="news", title="News title", processed_at=now), "/a.json")
        catalog.insert(_make_result(sha="b" * 64, source="gov", title="Gov title", processed_at=now), "/b.json")
        titles = catalog.get_recent_titles(source="news", hours=1)
        assert "News title" in titles
        assert "Gov title" not in titles


class TestCount:
    def test_count_all(self, catalog):
        assert catalog.count() == 0
        catalog.insert(_make_result(sha="a" * 64), "/a.json")
        catalog.insert(_make_result(sha="b" * 64), "/b.json")
        assert catalog.count() == 2

    def test_count_by_source(self, catalog):
        catalog.insert(_make_result(sha="a" * 64, source="news"), "/a.json")
        catalog.insert(_make_result(sha="b" * 64, source="gov"), "/b.json")
        assert catalog.count(source="news") == 1


class TestRemove:
    def test_remove_existing(self, catalog):
        r = _make_result()
        catalog.insert(r, "/a.json")
        assert catalog.remove(r["sha256"]) is True
        assert catalog.has(r["sha256"]) is False

    def test_remove_nonexistent(self, catalog):
        assert catalog.remove("x" * 64) is False
