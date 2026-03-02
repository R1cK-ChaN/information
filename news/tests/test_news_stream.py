"""Tests for the NewsStream orchestrator."""

import json

import pytest
import httpx
import respx
from src.news_stream import NewsStream


SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Fed announces emergency rate cut to support economy</title>
      <link>https://example.com/article/fed-emergency</link>
      <pubDate>Mon, 15 Jun 2025 12:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Gold price surges to record high amid uncertainty</title>
      <link>https://example.com/article/gold-surge</link>
      <pubDate>Mon, 15 Jun 2025 13:00:00 GMT</pubDate>
    </item>
    <item>
      <title>New restaurant opens downtown with great reviews</title>
      <link>https://example.com/article/restaurant</link>
      <pubDate>Mon, 15 Jun 2025 14:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>"""


@pytest.fixture
def ns(tmp_path):
    """Create a NewsStream with temp dirs and in-memory DBs."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    config = tmp_path / "config.yaml"
    config.write_text(f"""
storage:
  sqlite_path: ":memory:"
  output_dir: "{output_dir}"

providers:
  rss:
    timeout_seconds: 5
    max_items_per_feed: 10
    enabled: true
  summarizer:
    api_key_env: "GROQ_API_KEY"
    model: "llama-3.1-8b-instant"
    max_tokens: 150

retry:
  max_retries: 3
  base_delay_seconds: 1

polling:
  default_interval_minutes: 15
  cooldown_minutes: 5
  max_consecutive_failures: 3

deduplicator:
  similarity_threshold: 0.6
  lookback_hours: 24
""")
    stream = NewsStream(config_path=config)
    # Override sync_store to in-memory
    from src.sync_store import SyncStore
    stream.sync_store = SyncStore(":memory:")
    # Override catalog to in-memory but keep output_dir
    from widgets.catalog import Catalog
    stream.catalog = Catalog(":memory:")
    yield stream
    stream.close()


class TestDescribe:
    def test_describe_returns_metadata(self, ns):
        info = ns.describe()
        assert info["name"] == "NewsStream"
        assert info["version"] == "0.1.0"
        assert info["total_feeds"] > 50
        assert "markets" in info["categories"]
        assert isinstance(info["stored_items"], int)

    def test_list_feeds(self, ns):
        feeds = ns.list_feeds("markets")
        assert len(feeds) == 7
        assert all(f["category"] == "markets" for f in feeds)

    def test_list_all_feeds(self, ns):
        feeds = ns.list_feeds()
        assert len(feeds) == ns.registry.feed_count()


class TestGetters:
    def test_get_latest_empty(self, ns):
        assert ns.get_latest() == []

    def test_get_headlines_empty(self, ns):
        assert ns.get_headlines("markets") == []

    def test_search_empty(self, ns):
        assert ns.search("anything") == []

    def test_get_counts_empty(self, ns):
        assert ns.get_counts() == []


@respx.mock
class TestRefresh:
    def test_refresh_single_category(self, ns):
        # Mock all feed URLs to return our sample RSS
        respx.route().mock(return_value=httpx.Response(200, text=SAMPLE_RSS))

        result = ns.refresh("markets")
        assert result["fetched"] > 0
        assert result["stored"] > 0
        assert isinstance(result["errors"], list)

    def test_refresh_writes_json_files(self, ns):
        respx.route().mock(return_value=httpx.Response(200, text=SAMPLE_RSS))

        ns.refresh("markets")
        # Check that JSON files exist in output dir
        json_files = list(ns._output_dir.glob("*/*.json"))
        assert len(json_files) > 0
        # Verify JSON content
        data = json.loads(json_files[0].read_text())
        assert "sha256" in data
        assert "title" in data

    def test_refresh_inserts_into_catalog(self, ns):
        respx.route().mock(return_value=httpx.Response(200, text=SAMPLE_RSS))

        ns.refresh("markets")
        assert ns.catalog.count(source="news") > 0

    def test_refresh_classifies_items(self, ns):
        respx.route().mock(return_value=httpx.Response(200, text=SAMPLE_RSS))

        ns.refresh("markets")
        items = ns.get_latest(n=50)

        # "emergency rate cut" should be classified as critical
        emergency = [i for i in items if i.get("title") and "emergency rate cut" in i["title"]]
        if emergency:
            assert emergency[0]["impact_level"] == "critical"

    def test_refresh_deduplicates(self, ns):
        respx.route().mock(return_value=httpx.Response(200, text=SAMPLE_RSS))

        result1 = ns.refresh("markets")
        stored1 = result1["stored"]

        # Second refresh should mostly dedup
        result2 = ns.refresh("markets")
        assert result2["duplicates"] > 0

    def test_refresh_handles_errors(self, ns):
        respx.route().mock(return_value=httpx.Response(500))

        result = ns.refresh("markets")
        assert len(result["errors"]) > 0
        assert result["stored"] == 0


class TestAdmin:
    def test_get_feed_status_empty(self, ns):
        status = ns.get_feed_status()
        assert isinstance(status, list)

    @respx.mock
    def test_get_feed_status_after_refresh(self, ns):
        respx.route().mock(return_value=httpx.Response(200, text=SAMPLE_RSS))
        ns.refresh("centralbanks")
        status = ns.get_feed_status()
        assert len(status) > 0

    def test_prune(self, ns):
        deleted = ns.prune(days=90)
        assert deleted == 0  # nothing to prune
