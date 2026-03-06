"""Tests for the Telegram real-time provider."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.telegram.provider import _truncate_title
from src.telegram.realtime import (
    TelegramRealtimeProvider,
    _extract_url_from_entities,
    _make_item_id,
)


# ── _truncate_title (shared with HTTP provider) ──────────────────────────────

class TestTruncateTitle:
    def test_short_sentence(self):
        assert _truncate_title("Rate cut announced.") == "Rate cut announced."

    def test_first_sentence_extracted(self):
        text = "Fed cuts rate by 50bp. Markets react strongly to the news."
        assert _truncate_title(text) == "Fed cuts rate by 50bp."

    def test_long_line_truncated(self):
        text = "A " * 200  # way over 120 chars
        result = _truncate_title(text)
        assert len(result) <= 122  # 120 + ellipsis

    def test_multiline_takes_first(self):
        text = "First line here.\nSecond line here."
        assert _truncate_title(text) == "First line here."

    def test_empty_string(self):
        assert _truncate_title("") == ""


# ── _make_item_id ────────────────────────────────────────────────────────────

class TestMakeItemId:
    def test_deterministic(self):
        assert _make_item_id("https://t.me/test/123") == _make_item_id("https://t.me/test/123")

    def test_different_urls_differ(self):
        assert _make_item_id("https://t.me/a/1") != _make_item_id("https://t.me/b/2")

    def test_length(self):
        assert len(_make_item_id("https://t.me/test/1")) == 16


# ── _extract_url_from_entities ────────────────────────────────────────────────

class TestExtractUrl:
    def test_entity_url(self):
        ent = SimpleNamespace(url="https://example.com/article")
        msg = SimpleNamespace(entities=[ent], media=None)
        assert _extract_url_from_entities(msg) == "https://example.com/article"

    def test_skips_tme_links(self):
        ent = SimpleNamespace(url="https://t.me/channel/123")
        msg = SimpleNamespace(entities=[ent], media=None)
        assert _extract_url_from_entities(msg) is None

    def test_webpage_media(self):
        webpage = SimpleNamespace(url="https://reuters.com/story")
        media = SimpleNamespace(webpage=webpage)
        msg = SimpleNamespace(entities=None, media=media)
        assert _extract_url_from_entities(msg) == "https://reuters.com/story"

    def test_no_entities_no_media(self):
        msg = SimpleNamespace(entities=None, media=None)
        assert _extract_url_from_entities(msg) is None


# ── _handle_message ──────────────────────────────────────────────────────────

class TestHandleMessage:
    @pytest.fixture
    def provider(self):
        channel_map = {
            "testchannel": {
                "feed_name": "TG Test",
                "feed_category": "markets",
            },
        }
        on_items = AsyncMock()
        p = TelegramRealtimeProvider(
            api_id=12345,
            api_hash="testhash",
            channel_map=channel_map,
            on_items=on_items,
        )
        return p

    def _make_event(self, text="Test message", username="testchannel", msg_id=42):
        """Create a mock Telethon NewMessage event."""
        msg = MagicMock()
        msg.text = text
        msg.id = msg_id
        msg.date = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        msg.entities = None
        msg.media = None

        chat = MagicMock()
        chat.username = username

        event = MagicMock()
        event.message = msg
        event.get_chat = AsyncMock(return_value=chat)

        return event

    @pytest.mark.asyncio
    async def test_converts_message_to_item(self, provider):
        event = self._make_event("Fed cuts rate by 50bp. Markets react.")
        await provider._handle_message(event)

        provider._on_items.assert_called_once()
        items = provider._on_items.call_args[0][0]
        assert len(items) == 1

        item = items[0]
        assert item["source"] == "TG Test"
        assert item["feed_category"] == "markets"
        assert item["title"] == "Fed cuts rate by 50bp."
        assert item["description"] == "Fed cuts rate by 50bp. Markets react."
        assert item["link"] == "https://t.me/testchannel/42"
        assert "published" in item
        assert "fetched_at" in item
        assert "item_id" in item

    @pytest.mark.asyncio
    async def test_empty_message_ignored(self, provider):
        event = self._make_event(text="")
        await provider._handle_message(event)
        provider._on_items.assert_not_called()

    @pytest.mark.asyncio
    async def test_whitespace_message_ignored(self, provider):
        event = self._make_event(text="   \n  ")
        await provider._handle_message(event)
        provider._on_items.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_channel_uses_username(self, provider):
        event = self._make_event("Hello world", username="unknownchannel")
        await provider._handle_message(event)

        items = provider._on_items.call_args[0][0]
        assert items[0]["source"] == "@unknownchannel"
        assert items[0]["feed_category"] == ""

    @pytest.mark.asyncio
    async def test_external_url_used_as_link(self, provider):
        event = self._make_event("Check this article")
        ent = SimpleNamespace(url="https://reuters.com/story")
        event.message.entities = [ent]

        await provider._handle_message(event)
        items = provider._on_items.call_args[0][0]
        assert items[0]["link"] == "https://reuters.com/story"

    @pytest.mark.asyncio
    async def test_callback_error_does_not_crash(self, provider):
        provider._on_items.side_effect = RuntimeError("callback failed")
        event = self._make_event("Test message")
        # Should not raise
        await provider._handle_message(event)
