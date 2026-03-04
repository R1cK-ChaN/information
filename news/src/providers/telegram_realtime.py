"""Real-time Telegram channel listener using Telethon.

Connects to the Telegram API with a user session and listens for new
messages in monitored channels.  Each message is converted to the same
item dict format produced by ``TelegramProvider.fetch()`` and forwarded
to an async callback for batched processing.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable

from telethon import TelegramClient, events
from telethon.tl.types import Channel

from .telegram import _truncate_title

logger = logging.getLogger(__name__)


def _make_item_id(permalink: str) -> str:
    return hashlib.sha256(permalink.encode()).hexdigest()[:16]


class TelegramRealtimeProvider:
    """Telethon-based real-time listener for Telegram channels.

    Parameters
    ----------
    api_id : int
        Telegram API application ID.
    api_hash : str
        Telegram API application hash.
    channel_map : dict[str, dict]
        Mapping of channel username (lowercase) to
        ``{"feed_name": ..., "feed_category": ...}``.
    on_items : async callable
        ``async def callback(items: list[dict]) -> None`` invoked for
        every incoming message (single-item list).
    session_path : str
        Path to the ``.session`` file (without extension).
    """

    def __init__(
        self,
        api_id: int,
        api_hash: str,
        channel_map: dict[str, dict],
        on_items: Callable[[list[dict]], Awaitable[None]],
        session_path: str = "data/telegram_session/news_stream",
    ) -> None:
        self._api_id = api_id
        self._api_hash = api_hash
        self._channel_map = channel_map
        self._on_items = on_items
        self._session_path = session_path
        self._client: TelegramClient | None = None
        self._connected = False
        self._channel_ids: set[int] = set()

    # ── lifecycle ─────────────────────────────────────────────────

    async def start(self) -> None:
        """Connect, resolve channel IDs, register message handler."""
        self._client = TelegramClient(
            self._session_path, self._api_id, self._api_hash,
        )
        await self._client.connect()

        if not await self._client.is_user_authorized():
            raise RuntimeError(
                "Telegram session not authorized. "
                "Run `python -m src.telegram_login` first."
            )

        # Resolve channel usernames → numeric IDs for fast filtering
        for username in self._channel_map:
            try:
                entity = await self._client.get_entity(username)
                if isinstance(entity, Channel):
                    self._channel_ids.add(entity.id)
                else:
                    logger.warning(
                        "Telegram entity @%s is not a channel (type=%s), skipping",
                        username, type(entity).__name__,
                    )
            except Exception as exc:
                logger.warning("Failed to resolve @%s: %s", username, exc)

        if not self._channel_ids:
            raise RuntimeError("No Telegram channels could be resolved")

        self._client.add_event_handler(
            self._handle_message,
            events.NewMessage(chats=list(self._channel_ids)),
        )
        self._connected = True
        logger.info(
            "Telegram real-time connected: monitoring %d channels",
            len(self._channel_ids),
        )

    async def stop(self) -> None:
        """Disconnect the Telethon client."""
        self._connected = False
        if self._client:
            await self._client.disconnect()
            self._client = None
        logger.info("Telegram real-time disconnected")

    @property
    def connected(self) -> bool:
        """True when the client is connected and listening."""
        if self._client is None:
            return False
        return self._connected and self._client.is_connected()

    # ── message handler ───────────────────────────────────────────

    async def _handle_message(self, event: events.NewMessage.Event) -> None:
        """Convert a Telethon Message into a standard item dict."""
        msg = event.message
        text = msg.text or ""
        if not text.strip():
            return

        # Identify channel
        chat = await event.get_chat()
        username = (getattr(chat, "username", None) or "").lower()
        feed_info = self._channel_map.get(username, {})
        feed_name = feed_info.get("feed_name", f"@{username}")
        feed_category = feed_info.get("feed_category", "")

        permalink = f"https://t.me/{username}/{msg.id}" if username else ""
        if not permalink:
            return

        published = (
            msg.date.astimezone(timezone.utc).isoformat()
            if msg.date else datetime.now(timezone.utc).isoformat()
        )
        now = datetime.now(timezone.utc).isoformat()

        # Extract first external URL from message entities
        link = _extract_url_from_entities(msg) or permalink

        item = {
            "item_id": _make_item_id(permalink),
            "source": feed_name,
            "title": _truncate_title(text),
            "description": text,
            "link": link,
            "published": published,
            "fetched_at": now,
            "feed_category": feed_category,
        }

        try:
            await self._on_items([item])
        except Exception:
            logger.exception("Error in on_items callback")


def _extract_url_from_entities(msg) -> str | None:
    """Extract the first external URL from message entities."""
    if msg.entities:
        for ent in msg.entities:
            url = getattr(ent, "url", None)
            if url and "t.me" not in url:
                return url
    if msg.media and hasattr(msg.media, "webpage") and msg.media.webpage:
        wp_url = getattr(msg.media.webpage, "url", None)
        if wp_url and "t.me" not in wp_url:
            return wp_url
    return None
