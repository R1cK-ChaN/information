"""Feed registry: merged RSS + Telegram feed lists and queryable Registry class."""

from .feed_info import FeedInfo
from .rss.feeds import RSS_FEEDS
from .telegram.feeds import TG_FEEDS

# ── Combined feed list ─────────────────────────────────────────
FEEDS: list[FeedInfo] = RSS_FEEDS + TG_FEEDS


# ── Category index ─────────────────────────────────────────────
_BY_CATEGORY: dict[str, list[FeedInfo]] = {}
_BY_NAME: dict[str, FeedInfo] = {}

for _f in FEEDS:
    _BY_CATEGORY.setdefault(_f.category, []).append(_f)
    _BY_NAME[_f.name] = _f

CATEGORIES = sorted(_BY_CATEGORY.keys())


class Registry:
    """Queryable registry of news feed definitions."""

    def list_feeds(self, category: str | None = None) -> list[FeedInfo]:
        if category:
            return list(_BY_CATEGORY.get(category, []))
        return list(FEEDS)

    def get_feed(self, name: str) -> FeedInfo:
        if name not in _BY_NAME:
            raise KeyError(f"Unknown feed: {name}")
        return _BY_NAME[name]

    def list_categories(self) -> list[str]:
        return list(CATEGORIES)

    def feed_count(self) -> int:
        return len(FEEDS)
