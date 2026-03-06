"""FeedInfo dataclass — shared by registry, rss.feeds, and telegram.feeds."""

from dataclasses import dataclass


@dataclass(frozen=True)
class FeedInfo:
    name: str
    url: str
    category: str
