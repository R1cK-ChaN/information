"""NewsStream — main entry point for macro-finance news ingestion and querying."""

import logging
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml
from dotenv import load_dotenv

from .storage import Storage
from .registry import Registry, FeedInfo
from .classifier import classify
from .deduplicator import Deduplicator
from .providers.rss import RSSProvider
from .providers.summarizer import Summarizer
from .export import export_items

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class NewsStream:
    """Centralized news stream for macro finance research.

    Usage:
        ns = NewsStream()
        ns.refresh("centralbanks")
        headlines = ns.get_latest(n=20)
        counts = ns.get_counts(start="2025-01-01")
    """

    def __init__(self, config_path: str | Path | None = None):
        load_dotenv(_PROJECT_ROOT / ".env")

        if config_path is None:
            config_path = _PROJECT_ROOT / "config" / "news_stream.yaml"
        with open(config_path) as f:
            self.config = yaml.safe_load(f)

        # Storage
        db_path = _PROJECT_ROOT / self.config["storage"]["sqlite_path"]
        self.storage = Storage(db_path)

        # Registry
        self.registry = Registry()

        # RSS provider
        rss_cfg = self.config["providers"]["rss"]
        self.rss = RSSProvider(
            timeout=rss_cfg.get("timeout_seconds", 15),
            max_items=rss_cfg.get("max_items_per_feed", 10),
        )

        # Summarizer (optional)
        sum_cfg = self.config["providers"].get("summarizer", {})
        self.summarizer = Summarizer(
            model=sum_cfg.get("model", "llama-3.1-8b-instant"),
            max_tokens=sum_cfg.get("max_tokens", 150),
        )

        # Dedup config
        dedup_cfg = self.config.get("deduplicator", {})
        self._dedup_threshold = dedup_cfg.get("similarity_threshold", 0.6)
        self._dedup_lookback = dedup_cfg.get("lookback_hours", 24)

        # Polling config
        polling_cfg = self.config.get("polling", {})
        self._cooldown_minutes = polling_cfg.get("cooldown_minutes", 5)
        self._max_failures = polling_cfg.get("max_consecutive_failures", 3)

    # ── Retrieval ──────────────────────────────────────────────

    def get_latest(self, n: int = 20, impact_level: str | None = None) -> list[dict]:
        """Get the N most recent news items."""
        return self.storage.get_latest(n, impact_level)

    def get_headlines(
        self,
        category: str,
        n: int = 20,
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict]:
        """Get headlines for a feed category with optional date range."""
        return self.storage.get_headlines(category, n, start, end)

    def search(
        self,
        query: str,
        limit: int = 20,
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict]:
        """Search news items by title."""
        return self.storage.search(query, limit, start, end)

    def get_counts(
        self,
        start: str | None = None,
        end: str | None = None,
        category: str | None = None,
    ) -> list[dict]:
        """Query daily article counts for time-series analysis."""
        return self.storage.get_counts(start, end, category)

    # ── Export ─────────────────────────────────────────────────

    def export(
        self,
        extraction_path: str | Path | None = None,
        category: str | None = None,
        impact_level: str | None = None,
        n: int = 100,
        force: bool = False,
    ) -> dict:
        """Export news items to doc_parser extraction format.

        Args:
            extraction_path: Target directory. Defaults to ../doc_parser/data/extraction.
            category: Optional feed_category filter.
            impact_level: Optional impact_level filter.
            n: Max items to export.
            force: Overwrite existing extractions.

        Returns:
            Stats dict: {"exported": N, "skipped": N, "total": N}
        """
        if extraction_path is None:
            extraction_path = _PROJECT_ROOT.parent / "doc_parser" / "data" / "extraction"
        extraction_path = Path(extraction_path)

        items = self.storage.get_latest(n, impact_level)
        if category:
            items = [i for i in items if i.get("feed_category") == category]

        return export_items(items, extraction_path, force=force)

    # ── Ingestion ──────────────────────────────────────────────

    def refresh(self, category: str | None = None) -> dict:
        """Fetch, classify, dedup, and store news from feeds.

        Args:
            category: Optional feed category to refresh. If None, refreshes all.

        Returns:
            Summary dict with counts.
        """
        feeds = self.registry.list_feeds(category)
        if not feeds:
            return {"fetched": 0, "stored": 0, "duplicates": 0, "errors": []}

        # Seed deduplicator from recent stored titles
        dedup = Deduplicator(threshold=self._dedup_threshold)
        recent_titles = self.storage.get_recent_titles(self._dedup_lookback)
        dedup.seed(recent_titles)

        results = {"fetched": 0, "stored": 0, "duplicates": 0, "errors": []}

        for feed in feeds:
            if self._is_in_cooldown(feed.name):
                continue

            try:
                raw_items = self.rss.fetch_with_retry(
                    feed.url,
                    feed_name=feed.name,
                    feed_category=feed.category,
                )
                results["fetched"] += len(raw_items)

                # Classify and dedup
                to_store = []
                for item in raw_items:
                    if dedup.is_duplicate(item["title"]):
                        results["duplicates"] += 1
                        continue

                    cls = classify(item["title"])
                    item["impact_level"] = cls.impact_level
                    item["finance_category"] = cls.finance_category
                    item["confidence"] = cls.confidence
                    to_store.append(item)

                # Persist
                inserted = self.storage.upsert_items(to_store)
                results["stored"] += inserted

                # Update daily counts for newly inserted items
                if inserted > 0:
                    self.storage.update_daily_counts(to_store[:inserted])

                # Update sync log
                last_date = to_store[0]["published"] if to_store else None
                self.storage.update_sync(feed.name, last_item_date=last_date)

                logger.info(
                    "Refreshed %s: %d fetched, %d stored",
                    feed.name, len(raw_items), inserted,
                )

            except Exception as e:
                results["errors"].append(f"{feed.name}: {e}")
                self.storage.update_sync(feed.name, error=True)
                self._maybe_cooldown(feed.name)
                logger.warning("Failed to fetch %s: %s", feed.name, e)

            time.sleep(0.3)  # rate limit courtesy

        return results

    def bootstrap(self) -> dict:
        """Initial full fetch of all feeds across all categories."""
        logger.info("Bootstrap: fetching all %d feeds...", self.registry.feed_count())
        result = self.refresh()
        logger.info(
            "Bootstrap complete: %d fetched, %d stored, %d errors",
            result["fetched"], result["stored"], len(result["errors"]),
        )
        return result

    def _is_in_cooldown(self, feed_name: str) -> bool:
        """Check if a feed is in cooldown after repeated failures."""
        info = self.storage.get_sync_info(feed_name)
        if not info or not info.get("cooldown_until"):
            return False
        cooldown = datetime.fromisoformat(info["cooldown_until"])
        if cooldown.tzinfo is None:
            cooldown = cooldown.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) < cooldown

    def _maybe_cooldown(self, feed_name: str):
        """Set cooldown if consecutive failures exceed threshold."""
        info = self.storage.get_sync_info(feed_name)
        if info and info.get("consecutive_failures", 0) >= self._max_failures:
            until = (
                datetime.now(timezone.utc) + timedelta(minutes=self._cooldown_minutes)
            ).isoformat()
            self.storage.set_cooldown(feed_name, until)
            logger.warning("Feed %s in cooldown until %s", feed_name, until)

    # ── LLM (optional) ────────────────────────────────────────

    def summarize_latest(self, n: int = 10) -> str | None:
        """Summarize the latest N unsummarized items using Groq LLM."""
        if not self.summarizer.available:
            logger.info("Summarizer not available (no GROQ_API_KEY)")
            return None

        items = self.storage.get_items_without_summary(n)
        if not items:
            return None

        summaries = self.summarizer.summarize_batch(items)
        for item_id, summary in summaries:
            if summary:
                self.storage.update_summary(item_id, summary)

        return f"Summarized {sum(1 for _, s in summaries if s)} of {len(items)} items"

    # ── Admin ──────────────────────────────────────────────────

    def get_feed_status(self) -> list[dict]:
        """Get sync status for all feeds."""
        return self.storage.get_all_sync_info()

    def list_feeds(self, category: str | None = None) -> list[dict]:
        """List registered feeds."""
        feeds = self.registry.list_feeds(category)
        return [{"name": f.name, "url": f.url, "category": f.category} for f in feeds]

    def describe(self) -> dict:
        """Return module metadata and stats."""
        return {
            "name": "NewsStream",
            "version": "0.1.0",
            "total_feeds": self.registry.feed_count(),
            "categories": self.registry.list_categories(),
            "stored_items": self.storage.item_count(),
            "summarizer_available": self.summarizer.available,
        }

    def prune(self, days: int = 90) -> int:
        """Delete news items older than N days."""
        deleted = self.storage.prune(days)
        logger.info("Pruned %d items older than %d days", deleted, days)
        return deleted

    def close(self):
        """Close all connections."""
        self.rss.close()
        self.summarizer.close()
        self.storage.close()
