"""RSS feed polling for automatic report discovery."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import feedparser

logger = logging.getLogger(__name__)


@dataclass
class RSSItem:
    """A discovered report from an RSS feed."""

    url: str
    title: str
    published: str
    source_id: str
    feed_key: str


# RSS feed configurations: feed_key → {url, keyword_map}
# keyword_map maps keyword patterns to source_ids
RSS_FEEDS: dict[str, dict] = {
    "bea_news": {
        "url": "https://www.bea.gov/news/rss.xml",
        "keyword_map": {
            "gross domestic product": "us_bea_gdp",
            "gdp": "us_bea_gdp",
            "personal income": "us_bea_pce",
            "personal consumption": "us_bea_pce",
            "pce": "us_bea_pce",
            "trade": "us_bea_trade",
            "international trade": "us_bea_trade",
        },
    },
    "bls_latest": {
        "url": "https://www.bls.gov/feed/bls_latest.rss",
        "keyword_map": {
            "consumer price index": "us_bls_cpi",
            "cpi": "us_bls_cpi",
            "producer price index": "us_bls_ppi",
            "ppi": "us_bls_ppi",
            "employment situation": "us_bls_nfp",
            "nonfarm payroll": "us_bls_nfp",
        },
    },
    "fed_press": {
        "url": "https://www.federalreserve.gov/feeds/press_monetary.xml",
        "keyword_map": {
            "fomc statement": "us_fed_fomc_statement",
            "federal funds": "us_fed_fomc_statement",
            "minutes": "us_fed_fomc_minutes",
            "beige book": "us_fed_beigebook",
            "industrial production": "us_fed_ip",
        },
    },
    "census_economic": {
        "url": "https://www.census.gov/economic-indicators/indicator.xml",
        "keyword_map": {
            "retail": "us_census_retail",
            "advance monthly sales": "us_census_retail",
            "housing": "us_census_housing",
            "new residential": "us_census_housing",
            "building permits": "us_census_housing",
        },
    },
}


def _match_source_id(title: str, keyword_map: dict[str, str]) -> str | None:
    """Match an RSS item title to a source_id using keyword map."""
    title_lower = title.lower()
    for keyword, source_id in keyword_map.items():
        if keyword in title_lower:
            return source_id
    return None


async def poll_feed(feed_key: str) -> list[RSSItem]:
    """Poll a single RSS feed and return matched items."""
    cfg = RSS_FEEDS.get(feed_key)
    if not cfg:
        raise ValueError(f"Unknown RSS feed: {feed_key}")

    feed = feedparser.parse(cfg["url"])
    items = []

    for entry in feed.entries:
        title = entry.get("title", "")
        source_id = _match_source_id(title, cfg["keyword_map"])
        if source_id:
            link = entry.get("link", "")
            published = entry.get("published", "")
            items.append(
                RSSItem(
                    url=link,
                    title=title,
                    published=published,
                    source_id=source_id,
                    feed_key=feed_key,
                )
            )
            logger.info("RSS match: %s → %s", title[:60], source_id)

    return items


async def poll_all_feeds() -> list[RSSItem]:
    """Poll all configured RSS feeds."""
    all_items = []
    for feed_key in RSS_FEEDS:
        try:
            items = await poll_feed(feed_key)
            all_items.extend(items)
        except Exception as exc:
            logger.error("Failed to poll RSS feed %s: %s", feed_key, exc)
    return all_items
