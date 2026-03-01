"""SQLite storage layer for news stream data."""

import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS news_items (
    item_id          TEXT PRIMARY KEY,
    source           TEXT NOT NULL,
    title            TEXT NOT NULL,
    link             TEXT NOT NULL,
    published        TEXT NOT NULL,
    fetched_at       TEXT NOT NULL,
    feed_category    TEXT NOT NULL,
    impact_level     TEXT NOT NULL DEFAULT 'info',
    finance_category TEXT NOT NULL DEFAULT 'general',
    confidence       REAL NOT NULL DEFAULT 0.3,
    summary          TEXT
);
CREATE INDEX IF NOT EXISTS idx_news_published ON news_items(published);
CREATE INDEX IF NOT EXISTS idx_news_feed_cat  ON news_items(feed_category, published);
CREATE INDEX IF NOT EXISTS idx_news_fin_cat   ON news_items(finance_category, published);
CREATE INDEX IF NOT EXISTS idx_news_impact    ON news_items(impact_level, published);
CREATE INDEX IF NOT EXISTS idx_news_source    ON news_items(source);

CREATE TABLE IF NOT EXISTS daily_counts (
    date             TEXT NOT NULL,
    feed_category    TEXT NOT NULL,
    finance_category TEXT NOT NULL,
    impact_level     TEXT NOT NULL,
    count            INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (date, feed_category, finance_category, impact_level)
);

CREATE TABLE IF NOT EXISTS sync_log (
    feed_name            TEXT PRIMARY KEY,
    last_fetch           TEXT,
    last_item_date       TEXT,
    fetch_count          INTEGER DEFAULT 0,
    error_count          INTEGER DEFAULT 0,
    consecutive_failures INTEGER DEFAULT 0,
    cooldown_until       TEXT
);
"""


class Storage:
    """SQLite-backed persistent storage for news items."""

    def __init__(self, db_path: str | Path = ":memory:"):
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    # ── Ingestion ──────────────────────────────────────────────

    def upsert_items(self, items: list[dict]) -> int:
        """Insert or ignore news items. Returns count of newly inserted rows."""
        if not items:
            return 0
        inserted = 0
        for item in items:
            try:
                self.conn.execute(
                    """INSERT OR IGNORE INTO news_items
                       (item_id, source, title, link, published, fetched_at,
                        feed_category, impact_level, finance_category, confidence, summary)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        item["item_id"],
                        item["source"],
                        item["title"],
                        item["link"],
                        item["published"],
                        item["fetched_at"],
                        item["feed_category"],
                        item.get("impact_level", "info"),
                        item.get("finance_category", "general"),
                        item.get("confidence", 0.3),
                        item.get("summary"),
                    ),
                )
                inserted += self.conn.execute("SELECT changes()").fetchone()[0]
            except sqlite3.IntegrityError:
                pass
        self.conn.commit()
        return inserted

    def update_daily_counts(self, items: list[dict]):
        """Increment daily_counts for a batch of newly inserted items."""
        if not items:
            return
        counts: dict[tuple, int] = {}
        for item in items:
            date_str = item["published"][:10]
            key = (
                date_str,
                item["feed_category"],
                item.get("finance_category", "general"),
                item.get("impact_level", "info"),
            )
            counts[key] = counts.get(key, 0) + 1

        for (date, feed_cat, fin_cat, impact), count in counts.items():
            self.conn.execute(
                """INSERT INTO daily_counts (date, feed_category, finance_category, impact_level, count)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(date, feed_category, finance_category, impact_level)
                   DO UPDATE SET count = count + excluded.count""",
                (date, feed_cat, fin_cat, impact, count),
            )
        self.conn.commit()

    def update_summary(self, item_id: str, summary: str):
        """Set the LLM summary for a news item."""
        self.conn.execute(
            "UPDATE news_items SET summary = ? WHERE item_id = ?",
            (summary, item_id),
        )
        self.conn.commit()

    # ── Queries ────────────────────────────────────────────────

    def get_latest(self, n: int = 20, impact_level: str | None = None) -> list[dict]:
        """Get the N most recent news items, optionally filtered by impact."""
        query = "SELECT * FROM news_items"
        params: list = []
        if impact_level:
            query += " WHERE impact_level = ?"
            params.append(impact_level)
        query += " ORDER BY published DESC LIMIT ?"
        params.append(n)
        return [dict(row) for row in self.conn.execute(query, params).fetchall()]

    def get_headlines(
        self,
        category: str,
        n: int = 20,
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict]:
        """Get headlines for a feed_category with optional date range."""
        query = "SELECT * FROM news_items WHERE feed_category = ?"
        params: list = [category]
        if start:
            query += " AND published >= ?"
            params.append(start)
        if end:
            query += " AND published <= ?"
            params.append(end)
        query += " ORDER BY published DESC LIMIT ?"
        params.append(n)
        return [dict(row) for row in self.conn.execute(query, params).fetchall()]

    def search(
        self,
        query_str: str,
        limit: int = 20,
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict]:
        """Search news items by title (LIKE match)."""
        query = "SELECT * FROM news_items WHERE title LIKE ?"
        params: list = [f"%{query_str}%"]
        if start:
            query += " AND published >= ?"
            params.append(start)
        if end:
            query += " AND published <= ?"
            params.append(end)
        query += " ORDER BY published DESC LIMIT ?"
        params.append(limit)
        return [dict(row) for row in self.conn.execute(query, params).fetchall()]

    def get_counts(
        self,
        start: str | None = None,
        end: str | None = None,
        category: str | None = None,
    ) -> list[dict]:
        """Query daily_counts time-series."""
        query = "SELECT * FROM daily_counts WHERE 1=1"
        params: list = []
        if start:
            query += " AND date >= ?"
            params.append(start)
        if end:
            query += " AND date <= ?"
            params.append(end)
        if category:
            query += " AND feed_category = ?"
            params.append(category)
        query += " ORDER BY date"
        return [dict(row) for row in self.conn.execute(query, params).fetchall()]

    def get_recent_titles(self, hours: int = 24) -> list[str]:
        """Get titles from the last N hours for dedup seeding."""
        query = """
            SELECT title FROM news_items
            WHERE published >= datetime('now', ?)
            ORDER BY published DESC
        """
        rows = self.conn.execute(query, (f"-{hours} hours",)).fetchall()
        return [row["title"] for row in rows]

    def get_items_without_summary(self, n: int = 10) -> list[dict]:
        """Get recent items that lack an LLM summary."""
        query = """
            SELECT * FROM news_items
            WHERE summary IS NULL
            ORDER BY published DESC LIMIT ?
        """
        return [dict(row) for row in self.conn.execute(query, (n,)).fetchall()]

    # ── Sync log ───────────────────────────────────────────────

    def get_sync_info(self, feed_name: str) -> dict | None:
        """Read sync_log entry for a feed."""
        row = self.conn.execute(
            "SELECT * FROM sync_log WHERE feed_name = ?", (feed_name,)
        ).fetchone()
        return dict(row) if row else None

    def update_sync(
        self,
        feed_name: str,
        last_item_date: str | None = None,
        error: bool = False,
    ):
        """Update sync_log after a fetch attempt."""
        now = datetime.now(timezone.utc).isoformat()
        existing = self.get_sync_info(feed_name)

        if existing is None:
            self.conn.execute(
                """INSERT INTO sync_log
                   (feed_name, last_fetch, last_item_date, fetch_count, error_count, consecutive_failures)
                   VALUES (?, ?, ?, 1, ?, ?)""",
                (feed_name, now, last_item_date, 1 if error else 0, 1 if error else 0),
            )
        elif error:
            self.conn.execute(
                """UPDATE sync_log
                   SET last_fetch = ?, error_count = error_count + 1,
                       consecutive_failures = consecutive_failures + 1
                   WHERE feed_name = ?""",
                (now, feed_name),
            )
        else:
            self.conn.execute(
                """UPDATE sync_log
                   SET last_fetch = ?, last_item_date = ?,
                       fetch_count = fetch_count + 1, consecutive_failures = 0
                   WHERE feed_name = ?""",
                (now, last_item_date or existing["last_item_date"], feed_name),
            )
        self.conn.commit()

    def set_cooldown(self, feed_name: str, until: str):
        """Set cooldown_until for a feed after repeated failures."""
        self.conn.execute(
            "UPDATE sync_log SET cooldown_until = ? WHERE feed_name = ?",
            (until, feed_name),
        )
        self.conn.commit()

    def get_all_sync_info(self) -> list[dict]:
        """Get sync status for all feeds."""
        rows = self.conn.execute("SELECT * FROM sync_log ORDER BY feed_name").fetchall()
        return [dict(row) for row in rows]

    # ── Admin ──────────────────────────────────────────────────

    def prune(self, days: int = 90) -> int:
        """Delete news items older than N days. Returns count deleted."""
        cur = self.conn.execute(
            "DELETE FROM news_items WHERE published < datetime('now', ?)",
            (f"-{days} days",),
        )
        deleted = cur.rowcount
        # Also prune daily_counts
        self.conn.execute(
            "DELETE FROM daily_counts WHERE date < date('now', ?)",
            (f"-{days} days",),
        )
        self.conn.commit()
        return deleted

    def item_count(self) -> int:
        """Total number of stored news items."""
        return self.conn.execute("SELECT COUNT(*) FROM news_items").fetchone()[0]

    def close(self):
        """Close the SQLite connection."""
        self.conn.close()
