"""NewsStream — main entry point for macro-finance news ingestion and querying."""

import json
import logging
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml
from dotenv import load_dotenv

from .sync_store import SyncStore
from .registry import Registry, FeedInfo
from .classifier import classify
from .deduplicator import Deduplicator
from .providers.rss import RSSProvider
from .providers.summarizer import Summarizer
from .export import convert_item, save_extraction, _news_sha256

from widgets.catalog import Catalog

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

        # Sync store (feed polling state only)
        sync_db = _PROJECT_ROOT / self.config["storage"]["sqlite_path"]
        self.sync_store = SyncStore(sync_db)

        # Output dir for JSON files
        output_dir = self.config["storage"].get("output_dir", "../output")
        self._output_dir = (_PROJECT_ROOT / output_dir).resolve()
        self._output_dir.mkdir(parents=True, exist_ok=True)

        # Shared catalog
        self.catalog = Catalog(self._output_dir / "catalog.db")

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

    # ── Retrieval (delegated to catalog) ───────────────────────

    def get_latest(self, n: int = 20, impact_level: str | None = None) -> list[dict]:
        """Get the N most recent news items from catalog."""
        return self.catalog.get_latest(n, source="news", impact_level=impact_level)

    def get_headlines(
        self,
        category: str,
        n: int = 20,
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict]:
        """Get headlines for a feed category (searches catalog by title/source)."""
        # Use catalog search filtered by source
        return self.catalog.get_latest(n, source="news")

    def search(
        self,
        query: str,
        limit: int = 20,
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict]:
        """Search news items by title via catalog."""
        return self.catalog.search(query, limit)

    def get_counts(
        self,
        start: str | None = None,
        end: str | None = None,
        category: str | None = None,
    ) -> list[dict]:
        """Return item count from catalog."""
        count = self.catalog.count(source="news")
        if count == 0:
            return []
        return [{"source": "news", "count": count}]

    # ── Ingestion ──────────────────────────────────────────────

    def refresh(self, category: str | None = None) -> dict:
        """Fetch, classify, dedup, and store news from feeds.

        Items are written inline as JSON files + catalog entries.
        """
        feeds = self.registry.list_feeds(category)
        if not feeds:
            return {"fetched": 0, "stored": 0, "duplicates": 0, "errors": []}

        # Seed deduplicator from recent catalog titles
        dedup = Deduplicator(threshold=self._dedup_threshold)
        recent_titles = self.catalog.get_recent_titles(
            source="news", hours=self._dedup_lookback,
        )
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

                stored_in_feed = 0
                for item in raw_items:
                    if dedup.is_duplicate(item["title"]):
                        results["duplicates"] += 1
                        continue

                    # Classify
                    cls = classify(item["title"])
                    item["impact_level"] = cls.impact_level
                    item["finance_category"] = cls.finance_category
                    item["confidence"] = cls.confidence

                    # Convert to standardized JSON
                    result = convert_item(item)
                    sha = result["sha256"]

                    # Dedup via catalog
                    if self.catalog.has(sha):
                        results["duplicates"] += 1
                        continue

                    # Save JSON file
                    json_path = save_extraction(result, self._output_dir)

                    # Insert into catalog
                    self.catalog.insert(result, json_path)
                    stored_in_feed += 1

                results["stored"] += stored_in_feed

                # Update sync log
                last_date = raw_items[0]["published"] if raw_items else None
                self.sync_store.update_sync(feed.name, last_item_date=last_date)

                logger.info(
                    "Refreshed %s: %d fetched, %d stored",
                    feed.name, len(raw_items), stored_in_feed,
                )

            except Exception as e:
                results["errors"].append(f"{feed.name}: {e}")
                self.sync_store.update_sync(feed.name, error=True)
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
        info = self.sync_store.get_sync_info(feed_name)
        if not info or not info.get("cooldown_until"):
            return False
        cooldown = datetime.fromisoformat(info["cooldown_until"])
        if cooldown.tzinfo is None:
            cooldown = cooldown.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) < cooldown

    def _maybe_cooldown(self, feed_name: str):
        """Set cooldown if consecutive failures exceed threshold."""
        info = self.sync_store.get_sync_info(feed_name)
        if info and info.get("consecutive_failures", 0) >= self._max_failures:
            until = (
                datetime.now(timezone.utc) + timedelta(minutes=self._cooldown_minutes)
            ).isoformat()
            self.sync_store.set_cooldown(feed_name, until)
            logger.warning("Feed %s in cooldown until %s", feed_name, until)

    # ── LLM (optional) ────────────────────────────────────────

    def summarize_latest(self, n: int = 10) -> str | None:
        """Summarize the latest N unsummarized items using Groq LLM."""
        if not self.summarizer.available:
            logger.info("Summarizer not available (no GROQ_API_KEY)")
            return None

        # Get recent items without summary from catalog
        items = self.catalog.get_latest(n, source="news")
        if not items:
            return None

        # Filter to those without a summary in their JSON
        to_summarize = []
        for item in items:
            json_path = item.get("json_path")
            if not json_path:
                continue
            p = Path(json_path)
            if not p.exists():
                continue
            data = json.loads(p.read_text(encoding="utf-8"))
            if not data.get("summary"):
                to_summarize.append({"item_id": item["sha256"], "title": item["title"], **data})

        if not to_summarize:
            return None

        summaries = self.summarizer.summarize_batch(to_summarize)
        count = 0
        for item_id, summary in summaries:
            if summary:
                # Update the JSON file
                cat_item = [i for i in items if i["sha256"] == item_id]
                if cat_item:
                    jp = Path(cat_item[0]["json_path"])
                    if jp.exists():
                        data = json.loads(jp.read_text(encoding="utf-8"))
                        data["summary"] = summary
                        jp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                        count += 1

        return f"Summarized {count} of {len(to_summarize)} items"

    # ── Admin ──────────────────────────────────────────────────

    def get_feed_status(self) -> list[dict]:
        """Get sync status for all feeds."""
        return self.sync_store.get_all_sync_info()

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
            "stored_items": self.catalog.count(source="news"),
            "summarizer_available": self.summarizer.available,
        }

    def prune(self, days: int = 90) -> int:
        """Delete news items older than N days from catalog + JSON files."""
        cutoff = int(time.time()) - days * 86400
        # Find items to prune
        items = self.catalog.get_latest(10000, source="news")
        deleted = 0
        for item in items:
            if item.get("processed_at") and item["processed_at"] < cutoff:
                # Delete JSON file
                jp = item.get("json_path")
                if jp:
                    p = Path(jp)
                    if p.exists():
                        p.unlink()
                # Remove from catalog
                self.catalog.remove(item["sha256"])
                deleted += 1
        logger.info("Pruned %d items older than %d days", deleted, days)
        return deleted

    def close(self):
        """Close all connections."""
        self.rss.close()
        self.summarizer.close()
        self.sync_store.close()
        self.catalog.close()
