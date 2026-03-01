"""SQLite tracking store for fetch history and RSS sync state."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class SyncStore:
    """Lightweight SQLite store for dedup and RSS polling state."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS fetch_log (
                sha256         TEXT PRIMARY KEY,
                source_id      TEXT NOT NULL,
                url            TEXT NOT NULL,
                publish_date   TEXT,
                fetched_at     TEXT NOT NULL,
                status         TEXT NOT NULL DEFAULT 'ok',
                error_message  TEXT
            );
            CREATE TABLE IF NOT EXISTS rss_sync (
                feed_key       TEXT PRIMARY KEY,
                last_poll      TEXT NOT NULL,
                last_item_date TEXT,
                poll_count     INTEGER NOT NULL DEFAULT 0
            );
        """)

    def record_fetch(
        self,
        sha: str,
        source_id: str,
        url: str,
        publish_date: str | None,
        status: str = "ok",
        error_message: str | None = None,
    ) -> None:
        """Record a fetch attempt."""
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """INSERT OR REPLACE INTO fetch_log
               (sha256, source_id, url, publish_date, fetched_at, status, error_message)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (sha, source_id, url, publish_date, now, status, error_message),
        )
        self._conn.commit()

    def has_been_fetched(self, sha: str) -> bool:
        """Check if a sha has been successfully fetched."""
        row = self._conn.execute(
            "SELECT 1 FROM fetch_log WHERE sha256 = ? AND status = 'ok'",
            (sha,),
        ).fetchone()
        return row is not None

    def recent_fetches(self, limit: int = 20) -> list[dict]:
        """Return recent fetch log entries."""
        rows = self._conn.execute(
            "SELECT * FROM fetch_log ORDER BY fetched_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def update_rss_sync(
        self, feed_key: str, last_item_date: str | None = None
    ) -> None:
        """Update RSS poll tracking."""
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """INSERT INTO rss_sync (feed_key, last_poll, last_item_date, poll_count)
               VALUES (?, ?, ?, 1)
               ON CONFLICT(feed_key) DO UPDATE SET
                   last_poll = excluded.last_poll,
                   last_item_date = COALESCE(excluded.last_item_date, last_item_date),
                   poll_count = poll_count + 1""",
            (feed_key, now, last_item_date),
        )
        self._conn.commit()

    def get_rss_sync(self, feed_key: str) -> dict | None:
        """Get RSS sync state for a feed."""
        row = self._conn.execute(
            "SELECT * FROM rss_sync WHERE feed_key = ?", (feed_key,)
        ).fetchone()
        return dict(row) if row else None

    def close(self) -> None:
        self._conn.close()
