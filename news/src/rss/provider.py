"""RSS/Atom feed provider using feedparser + httpx."""

import hashlib
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import httpx

from ..common.base_provider import BaseProvider

logger = logging.getLogger(__name__)


def _make_item_id(link: str) -> str:
    """Generate a stable item ID from the link URL."""
    return hashlib.sha256(link.encode()).hexdigest()[:16]


def _parse_date(entry: dict) -> str:
    """Extract and normalize published date from a feed entry."""
    for field in ("published", "updated", "created"):
        raw = entry.get(field)
        if raw:
            try:
                dt = parsedate_to_datetime(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.isoformat()
            except Exception:
                pass
        # feedparser also provides *_parsed tuples
        parsed = entry.get(f"{field}_parsed")
        if parsed:
            try:
                import time as _time
                dt = datetime.fromtimestamp(_time.mktime(parsed), tz=timezone.utc)
                return dt.isoformat()
            except Exception:
                pass

    return datetime.now(timezone.utc).isoformat()


class RSSProvider(BaseProvider):
    """Fetches and parses RSS/Atom feeds."""

    provider_name = "rss"

    def __init__(self, timeout: int = 15, max_items: int = 10):
        self.timeout = timeout
        self.max_items = max_items
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": "NewsStream/0.1 (macro-finance-research)",
                "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
            },
        )

    def fetch(self, url: str, feed_name: str = "", feed_category: str = "") -> list[dict]:
        """Fetch and parse an RSS/Atom feed.

        Args:
            url: Feed URL.
            feed_name: Source name for attribution.
            feed_category: Category tag.

        Returns:
            List of parsed news item dicts.
        """
        response = self._client.get(url)
        response.raise_for_status()

        feed = feedparser.parse(response.text)

        if feed.bozo and not feed.entries:
            raise ValueError(f"Feed parse error for {url}: {feed.bozo_exception}")

        items = []
        now = datetime.now(timezone.utc).isoformat()

        for entry in feed.entries[: self.max_items]:
            link = entry.get("link", "")
            title = entry.get("title", "").strip()
            if not link or not title:
                continue

            # Extract description/summary from feed entry.
            # Prefer content:encoded (richer), fall back to summary/description.
            description = ""
            if entry.get("content"):
                description = entry["content"][0].get("value", "").strip()
            if not description:
                description = (entry.get("summary") or "").strip()

            items.append({
                "item_id": _make_item_id(link),
                "source": feed_name or feed.feed.get("title", "Unknown"),
                "title": title,
                "description": description,
                "link": link,
                "published": _parse_date(entry),
                "fetched_at": now,
                "feed_category": feed_category,
            })

        return items

    def close(self):
        """Close the HTTP client."""
        self._client.close()
