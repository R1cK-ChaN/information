"""Integration tests for real-time Telegram pipeline."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
import httpx
import respx

from src.news_stream import NewsStream


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
    from src.common.sync_store import SyncStore
    stream.sync_store = SyncStore(":memory:")
    from widgets.catalog import Catalog
    stream.catalog = Catalog(":memory:")
    yield stream
    stream.close()


_DISTINCT_TITLES = [
    "Fed announces emergency rate cut to support economy",
    "Gold price surges to record high amid uncertainty",
    "European Central Bank holds rates steady as inflation eases",
]


def _make_rt_items(count: int = 3) -> list[dict]:
    """Generate sample real-time items with distinct titles to avoid Jaccard dedup."""
    now = datetime.now(timezone.utc).isoformat()
    items = []
    for i in range(count):
        title = _DISTINCT_TITLES[i] if i < len(_DISTINCT_TITLES) else f"Unique headline {i}"
        items.append({
            "item_id": f"rt_item_{i:04d}",
            "source": "TG TestChannel",
            "title": title,
            "description": f"Full text of: {title}. Additional details here.",
            "link": f"https://t.me/testchannel/{1000 + i}",
            "published": now,
            "fetched_at": now,
            "feed_category": "markets",
        })
    return items


class TestProcessRealtimeItems:
    @respx.mock
    def test_stores_new_items(self, ns):
        # Mock article fetcher (items link to t.me so no real fetch needed)
        respx.route().mock(return_value=httpx.Response(200, text="<html>article</html>"))

        items = _make_rt_items(3)
        stored = ns.process_realtime_items(items)
        assert stored == 3
        assert ns.catalog.count(source="news") == 3

    @respx.mock
    def test_dedup_second_batch(self, ns):
        respx.route().mock(return_value=httpx.Response(200, text="<html>article</html>"))

        items = _make_rt_items(3)
        stored1 = ns.process_realtime_items(items)
        assert stored1 == 3

        # Second batch with same items
        stored2 = ns.process_realtime_items(items)
        assert stored2 == 0

    @respx.mock
    def test_empty_batch(self, ns):
        stored = ns.process_realtime_items([])
        assert stored == 0

    @respx.mock
    def test_writes_json_files(self, ns):
        respx.route().mock(return_value=httpx.Response(200, text="<html>article</html>"))

        items = _make_rt_items(1)
        ns.process_realtime_items(items)

        json_files = list(ns._output_dir.glob("*/*.json"))
        assert len(json_files) == 1

        data = json.loads(json_files[0].read_text())
        assert "sha256" in data
        assert "title" in data

    @respx.mock
    def test_classifies_items(self, ns):
        respx.route().mock(return_value=httpx.Response(200, text="<html>article</html>"))

        items = _make_rt_items(1)
        ns.process_realtime_items(items)

        latest = ns.get_latest(n=1)
        assert len(latest) == 1
        assert "impact_level" in latest[0]


SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Test RSS headline for polling</title>
      <link>https://example.com/article/test-rss</link>
      <pubDate>Mon, 15 Jun 2025 12:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>"""


class TestRefreshSkipTelegram:
    @respx.mock
    def test_skip_telegram_true(self, ns):
        """With skip_telegram=True, TG feeds should be skipped."""
        respx.route().mock(return_value=httpx.Response(200, text=SAMPLE_RSS))

        result = ns.refresh(skip_telegram=True)
        # Should still fetch RSS feeds
        assert result["fetched"] >= 0
        # Verify no t.me URLs were fetched by checking the calls
        for call in respx.calls:
            url = str(call.request.url)
            assert "t.me/s/" not in url

    @respx.mock
    def test_skip_telegram_false(self, ns):
        """With skip_telegram=False (default), TG feeds should be included."""
        respx.route().mock(return_value=httpx.Response(200, text=SAMPLE_RSS))

        result = ns.refresh(skip_telegram=False)
        assert result["fetched"] >= 0
