"""Telegram public channel provider using httpx + lxml."""

import hashlib
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
import lxml.html

from .base import BaseProvider

logger = logging.getLogger(__name__)

_TG_URL_RE = re.compile(r"https?://t\.me/s/(\w+)")


def _make_item_id(permalink: str) -> str:
    return hashlib.sha256(permalink.encode()).hexdigest()[:16]


def _truncate_title(text: str, max_len: int = 120) -> str:
    """Extract a title from message text: first sentence or truncated first line."""
    # Take first line
    first_line = text.split("\n", 1)[0].strip()
    # Try splitting on sentence-ending punctuation
    for sep in (". ", "! ", "? "):
        idx = first_line.find(sep)
        if 0 < idx < max_len:
            return first_line[: idx + 1]
    if len(first_line) <= max_len:
        return first_line
    return first_line[:max_len].rsplit(" ", 1)[0] + "…"


def _extract_external_url(message_el) -> str | None:
    """Find the first external (non-t.me) link in a message element."""
    for a_tag in message_el.cssselect("a[href]"):
        href = a_tag.get("href", "")
        if not href:
            continue
        parsed = urlparse(href)
        if parsed.scheme in ("http", "https") and "t.me" not in parsed.netloc:
            return href
    return None


class TelegramProvider(BaseProvider):
    """Scrapes public Telegram channel previews at t.me/s/<channel>."""

    provider_name = "telegram"

    def __init__(self, timeout: int = 15, max_items: int = 20):
        self.timeout = timeout
        self.max_items = max_items
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": "NewsStream/0.1 (macro-finance-research)",
                "Accept": "text/html",
            },
        )

    def fetch(self, url: str, feed_name: str = "", feed_category: str = "") -> list[dict]:
        """Fetch recent messages from a public Telegram channel.

        Args:
            url: https://t.me/s/<channel> URL.
            feed_name: Source name for attribution.
            feed_category: Category tag.

        Returns:
            List of parsed news item dicts matching RSSProvider output format.
        """
        m = _TG_URL_RE.match(url)
        if not m:
            raise ValueError(f"Invalid Telegram channel URL: {url}")
        channel = m.group(1)

        response = self._client.get(url)
        response.raise_for_status()

        doc = lxml.html.fromstring(response.text)
        messages = doc.cssselect("div.tgme_widget_message")

        items = []
        now = datetime.now(timezone.utc).isoformat()

        for msg in messages:
            data_post = msg.get("data-post", "")
            if not data_post:
                continue

            # Text content
            text_els = msg.cssselect(".tgme_widget_message_text")
            if not text_els:
                continue
            text = text_els[0].text_content().strip()
            if not text:
                continue

            # Permalink
            permalink = f"https://t.me/{data_post}"

            # Date
            time_els = msg.cssselect(".tgme_widget_message_date time[datetime]")
            published = now
            if time_els:
                dt_str = time_els[0].get("datetime", "")
                if dt_str:
                    try:
                        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                        published = dt.isoformat()
                    except ValueError:
                        pass

            # External link (for article_fetcher) or permalink fallback
            external_url = _extract_external_url(msg)
            link = external_url or permalink

            title = _truncate_title(text)

            items.append({
                "item_id": _make_item_id(permalink),
                "source": feed_name or f"@{channel}",
                "title": title,
                "description": text,
                "link": link,
                "published": published,
                "fetched_at": now,
                "feed_category": feed_category,
            })

            if len(items) >= self.max_items:
                break

        # Telegram HTML is oldest-first; reverse to match RSS newest-first order
        items.reverse()
        return items

    def close(self):
        """Close the HTTP client."""
        self._client.close()
