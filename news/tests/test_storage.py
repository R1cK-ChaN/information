"""Tests for the SQLite storage layer."""

import pytest
from src.storage import Storage


@pytest.fixture
def store():
    s = Storage(":memory:")
    yield s
    s.close()


def _make_item(
    item_id="abc123",
    source="TestFeed",
    title="Test headline",
    link="https://example.com/1",
    published="2025-06-15T12:00:00Z",
    feed_category="markets",
    impact_level="medium",
    finance_category="rates",
    confidence=0.7,
):
    return {
        "item_id": item_id,
        "source": source,
        "title": title,
        "link": link,
        "published": published,
        "fetched_at": "2025-06-15T12:05:00Z",
        "feed_category": feed_category,
        "impact_level": impact_level,
        "finance_category": finance_category,
        "confidence": confidence,
    }


class TestUpsertAndQuery:
    def test_upsert_inserts_new_items(self, store):
        items = [_make_item(), _make_item(item_id="def456", title="Another headline")]
        inserted = store.upsert_items(items)
        assert inserted == 2
        assert store.item_count() == 2

    def test_upsert_ignores_duplicates(self, store):
        items = [_make_item()]
        store.upsert_items(items)
        inserted = store.upsert_items(items)
        assert inserted == 0
        assert store.item_count() == 1

    def test_get_latest(self, store):
        items = [
            _make_item(item_id="a", published="2025-06-15T10:00:00Z"),
            _make_item(item_id="b", published="2025-06-15T12:00:00Z"),
            _make_item(item_id="c", published="2025-06-15T11:00:00Z"),
        ]
        store.upsert_items(items)
        latest = store.get_latest(n=2)
        assert len(latest) == 2
        assert latest[0]["item_id"] == "b"
        assert latest[1]["item_id"] == "c"

    def test_get_latest_with_impact_filter(self, store):
        items = [
            _make_item(item_id="a", impact_level="high"),
            _make_item(item_id="b", impact_level="low"),
        ]
        store.upsert_items(items)
        result = store.get_latest(impact_level="high")
        assert len(result) == 1
        assert result[0]["item_id"] == "a"

    def test_get_headlines_by_category(self, store):
        items = [
            _make_item(item_id="a", feed_category="markets"),
            _make_item(item_id="b", feed_category="forex"),
        ]
        store.upsert_items(items)
        result = store.get_headlines("markets")
        assert len(result) == 1
        assert result[0]["feed_category"] == "markets"

    def test_get_headlines_date_range(self, store):
        items = [
            _make_item(item_id="a", published="2025-06-10T10:00:00Z"),
            _make_item(item_id="b", published="2025-06-15T10:00:00Z"),
            _make_item(item_id="c", published="2025-06-20T10:00:00Z"),
        ]
        store.upsert_items(items)
        result = store.get_headlines("markets", start="2025-06-12", end="2025-06-18")
        assert len(result) == 1
        assert result[0]["item_id"] == "b"

    def test_search(self, store):
        items = [
            _make_item(item_id="a", title="Fed raises interest rates"),
            _make_item(item_id="b", title="Gold price surges"),
        ]
        store.upsert_items(items)
        result = store.search("interest rates")
        assert len(result) == 1
        assert result[0]["item_id"] == "a"

    def test_search_date_range(self, store):
        items = [
            _make_item(item_id="a", title="Fed cuts rates", published="2025-01-01T00:00:00Z"),
            _make_item(item_id="b", title="Fed cuts rates again", published="2025-06-01T00:00:00Z"),
        ]
        store.upsert_items(items)
        result = store.search("Fed cuts", start="2025-05-01")
        assert len(result) == 1
        assert result[0]["item_id"] == "b"


class TestDailyCounts:
    def test_update_and_query_counts(self, store):
        items = [
            _make_item(item_id="a", published="2025-06-15T10:00:00Z"),
            _make_item(item_id="b", published="2025-06-15T11:00:00Z"),
            _make_item(item_id="c", published="2025-06-16T10:00:00Z"),
        ]
        store.update_daily_counts(items)
        counts = store.get_counts()
        assert len(counts) == 2
        day15 = [c for c in counts if c["date"] == "2025-06-15"]
        assert day15[0]["count"] == 2

    def test_counts_accumulate(self, store):
        items1 = [_make_item(item_id="a")]
        items2 = [_make_item(item_id="b")]
        store.update_daily_counts(items1)
        store.update_daily_counts(items2)
        counts = store.get_counts()
        assert counts[0]["count"] == 2

    def test_counts_filter_by_category(self, store):
        items = [
            _make_item(item_id="a", feed_category="markets"),
            _make_item(item_id="b", feed_category="forex"),
        ]
        store.update_daily_counts(items)
        counts = store.get_counts(category="forex")
        assert len(counts) == 1
        assert counts[0]["feed_category"] == "forex"


class TestSyncLog:
    def test_initial_sync(self, store):
        store.update_sync("TestFeed", last_item_date="2025-06-15")
        info = store.get_sync_info("TestFeed")
        assert info is not None
        assert info["fetch_count"] == 1
        assert info["error_count"] == 0
        assert info["consecutive_failures"] == 0

    def test_sync_success_increments(self, store):
        store.update_sync("TestFeed", last_item_date="2025-06-15")
        store.update_sync("TestFeed", last_item_date="2025-06-16")
        info = store.get_sync_info("TestFeed")
        assert info["fetch_count"] == 2

    def test_sync_error(self, store):
        store.update_sync("TestFeed", last_item_date="2025-06-15")
        store.update_sync("TestFeed", error=True)
        info = store.get_sync_info("TestFeed")
        assert info["error_count"] == 1
        assert info["consecutive_failures"] == 1

    def test_sync_error_resets_on_success(self, store):
        store.update_sync("TestFeed", error=True)
        store.update_sync("TestFeed", last_item_date="2025-06-15")
        info = store.get_sync_info("TestFeed")
        assert info["consecutive_failures"] == 0

    def test_get_all_sync_info(self, store):
        store.update_sync("FeedA")
        store.update_sync("FeedB")
        all_info = store.get_all_sync_info()
        assert len(all_info) == 2


class TestAdmin:
    def test_update_summary(self, store):
        items = [_make_item()]
        store.upsert_items(items)
        store.update_summary("abc123", "A brief summary")
        result = store.get_latest(n=1)
        assert result[0]["summary"] == "A brief summary"

    def test_items_without_summary(self, store):
        items = [_make_item(item_id="a"), _make_item(item_id="b")]
        store.upsert_items(items)
        store.update_summary("a", "has summary")
        unsummarized = store.get_items_without_summary()
        assert len(unsummarized) == 1
        assert unsummarized[0]["item_id"] == "b"

    def test_item_count(self, store):
        assert store.item_count() == 0
        store.upsert_items([_make_item()])
        assert store.item_count() == 1
