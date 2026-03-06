"""Telegram channel feed definitions."""

from ..feed_info import FeedInfo


def _tg(channel: str) -> str:
    """Build a Telegram public channel preview URL."""
    return f"https://t.me/s/{channel}"


TG_FEEDS: list[FeedInfo] = [
    FeedInfo("TG Bloomberg", _tg("Bloomberg"), "markets"),
    FeedInfo("TG Nikkei Asia", _tg("NikkeiAsia"), "markets"),
    FeedInfo("TG CoinTelegraph", _tg("CoinTelegraph"), "crypto"),
    FeedInfo("TG Crypto", _tg("crypto"), "crypto"),
    FeedInfo("TG Xinhua", _tg("XHNews"), "china"),
    FeedInfo("TG SCMP", _tg("SCMPNews"), "china"),
    FeedInfo("TG Jin10", _tg("jin10data"), "china"),
    FeedInfo("TG Xinhua Reference", _tg("xhqcankao"), "china"),
    FeedInfo("TG TNews365", _tg("tnews365"), "china"),
    FeedInfo("TG BBC World", _tg("BBCWorld"), "global"),
    FeedInfo("TG Finance Magnates", _tg("financemagnatesnews"), "markets"),
    FeedInfo("TG Market News Feed", _tg("marketfeed"), "markets"),
]
