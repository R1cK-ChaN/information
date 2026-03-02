"""Tests for the feed registry."""

import pytest
from src.registry import Registry, FEEDS, CATEGORIES, FeedInfo


@pytest.fixture
def registry():
    return Registry()


class TestRegistry:
    def test_has_feeds(self, registry):
        assert registry.feed_count() >= 55

    def test_all_feeds_have_required_fields(self):
        for feed in FEEDS:
            assert feed.name
            assert feed.url
            assert feed.category
            assert feed.url.startswith("http")

    def test_categories_present(self, registry):
        cats = registry.list_categories()
        expected = [
            "markets", "forex", "bonds", "commodities", "crypto",
            "centralbanks", "economic", "ipo", "derivatives", "fintech",
            "regulation", "institutional", "analysis", "thinktanks", "government",
        ]
        for cat in expected:
            assert cat in cats, f"Missing category: {cat}"

    def test_list_feeds_by_category(self, registry):
        markets = registry.list_feeds("markets")
        assert len(markets) == 10
        assert all(f.category == "markets" for f in markets)

    def test_list_feeds_all(self, registry):
        all_feeds = registry.list_feeds()
        assert len(all_feeds) == registry.feed_count()

    def test_get_feed_by_name(self, registry):
        feed = registry.get_feed("CNBC")
        assert feed.category == "markets"
        assert "cnbc.com" in feed.url

    def test_get_feed_unknown_raises(self, registry):
        with pytest.raises(KeyError):
            registry.get_feed("NonexistentFeed")

    def test_direct_rss_feeds_present(self, registry):
        """Key feeds that have direct RSS (not Google News proxy)."""
        direct_feeds = ["CNBC", "Yahoo Finance", "CoinDesk", "Cointelegraph",
                        "Federal Reserve", "SEC", "Foreign Policy"]
        for name in direct_feeds:
            feed = registry.get_feed(name)
            assert "news.google.com" not in feed.url, f"{name} should be direct RSS"

    def test_feed_info_is_frozen(self):
        feed = FEEDS[0]
        with pytest.raises(AttributeError):
            feed.name = "changed"
