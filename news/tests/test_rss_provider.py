"""Tests for the RSS provider (mocked HTTP)."""

import pytest
import httpx
import respx
from src.rss.provider import RSSProvider, _make_item_id, _parse_date


SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Finance Feed</title>
    <item>
      <title>Fed raises rates by 25bps</title>
      <link>https://example.com/article/1</link>
      <pubDate>Mon, 15 Jun 2025 12:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Gold price surges</title>
      <link>https://example.com/article/2</link>
      <pubDate>Mon, 15 Jun 2025 13:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Bitcoin crosses $100k</title>
      <link>https://example.com/article/3</link>
      <pubDate>Mon, 15 Jun 2025 14:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>"""

SAMPLE_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Test Atom Feed</title>
  <entry>
    <title>ECB holds rates steady</title>
    <link href="https://example.com/atom/1"/>
    <updated>2025-06-15T15:00:00Z</updated>
  </entry>
</feed>"""


class TestItemId:
    def test_deterministic(self):
        id1 = _make_item_id("https://example.com/article/1")
        id2 = _make_item_id("https://example.com/article/1")
        assert id1 == id2

    def test_different_urls(self):
        id1 = _make_item_id("https://example.com/article/1")
        id2 = _make_item_id("https://example.com/article/2")
        assert id1 != id2

    def test_length(self):
        item_id = _make_item_id("https://example.com/article/1")
        assert len(item_id) == 16


class TestParseDate:
    def test_rfc822(self):
        entry = {"published": "Mon, 15 Jun 2025 12:00:00 GMT"}
        result = _parse_date(entry)
        assert "2025-06-15" in result

    def test_falls_back_to_updated(self):
        entry = {"updated": "Mon, 15 Jun 2025 12:00:00 GMT"}
        result = _parse_date(entry)
        assert "2025-06-15" in result

    def test_no_date_uses_now(self):
        result = _parse_date({})
        assert "T" in result  # ISO format


@respx.mock
class TestRSSProvider:
    def test_fetch_rss(self):
        respx.get("https://example.com/feed.xml").mock(
            return_value=httpx.Response(200, text=SAMPLE_RSS)
        )
        provider = RSSProvider(timeout=5, max_items=10)
        items = provider.fetch(
            "https://example.com/feed.xml",
            feed_name="TestFeed",
            feed_category="markets",
        )
        assert len(items) == 3
        assert items[0]["title"] == "Fed raises rates by 25bps"
        assert items[0]["source"] == "TestFeed"
        assert items[0]["feed_category"] == "markets"
        assert items[0]["item_id"]
        assert items[0]["link"] == "https://example.com/article/1"
        provider.close()

    def test_fetch_respects_max_items(self):
        respx.get("https://example.com/feed.xml").mock(
            return_value=httpx.Response(200, text=SAMPLE_RSS)
        )
        provider = RSSProvider(timeout=5, max_items=2)
        items = provider.fetch(
            "https://example.com/feed.xml",
            feed_name="TestFeed",
            feed_category="markets",
        )
        assert len(items) == 2
        provider.close()

    def test_fetch_atom(self):
        respx.get("https://example.com/atom.xml").mock(
            return_value=httpx.Response(200, text=SAMPLE_ATOM)
        )
        provider = RSSProvider(timeout=5)
        items = provider.fetch(
            "https://example.com/atom.xml",
            feed_name="AtomFeed",
            feed_category="centralbanks",
        )
        assert len(items) == 1
        assert items[0]["title"] == "ECB holds rates steady"
        provider.close()

    def test_fetch_http_error_raises(self):
        respx.get("https://example.com/bad.xml").mock(
            return_value=httpx.Response(500)
        )
        provider = RSSProvider(timeout=5)
        with pytest.raises(httpx.HTTPStatusError):
            provider.fetch("https://example.com/bad.xml")
        provider.close()

    def test_fetch_empty_feed(self):
        empty_rss = """<?xml version="1.0"?>
        <rss version="2.0"><channel><title>Empty</title></channel></rss>"""
        respx.get("https://example.com/empty.xml").mock(
            return_value=httpx.Response(200, text=empty_rss)
        )
        provider = RSSProvider(timeout=5)
        items = provider.fetch("https://example.com/empty.xml")
        assert items == []
        provider.close()

    def test_items_without_link_skipped(self):
        rss_no_link = """<?xml version="1.0"?>
        <rss version="2.0"><channel><title>Test</title>
        <item><title>No link item</title></item>
        <item><title>Has link</title><link>https://example.com/x</link></item>
        </channel></rss>"""
        respx.get("https://example.com/nolink.xml").mock(
            return_value=httpx.Response(200, text=rss_no_link)
        )
        provider = RSSProvider(timeout=5)
        items = provider.fetch("https://example.com/nolink.xml")
        assert len(items) == 1
        assert items[0]["title"] == "Has link"
        provider.close()
