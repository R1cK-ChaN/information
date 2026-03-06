"""Tests for the sync_store — feed polling state only."""

import pytest
from src.common.sync_store import SyncStore


@pytest.fixture
def store():
    s = SyncStore(":memory:")
    yield s
    s.close()


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


class TestCooldown:
    def test_set_cooldown(self, store):
        store.update_sync("TestFeed")
        store.set_cooldown("TestFeed", "2025-06-15T12:00:00+00:00")
        info = store.get_sync_info("TestFeed")
        assert info["cooldown_until"] == "2025-06-15T12:00:00+00:00"
