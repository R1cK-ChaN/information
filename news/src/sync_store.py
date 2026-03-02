"""Lightweight SQLite store for feed polling state and cooldown tracking.

This replaces the sync_log portion of the old ``storage.py``.  Item storage
has moved to the shared ``widgets.catalog.Catalog``.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
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


class SyncStore:
    """SQLite-backed feed polling state (no item storage)."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    # -- Sync log ------------------------------------------------------------

    def get_sync_info(self, feed_name: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM sync_log WHERE feed_name = ?", (feed_name,)
        ).fetchone()
        return dict(row) if row else None

    def update_sync(
        self,
        feed_name: str,
        last_item_date: str | None = None,
        error: bool = False,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        existing = self.get_sync_info(feed_name)

        if existing is None:
            self._conn.execute(
                """INSERT INTO sync_log
                   (feed_name, last_fetch, last_item_date,
                    fetch_count, error_count, consecutive_failures)
                   VALUES (?, ?, ?, 1, ?, ?)""",
                (feed_name, now, last_item_date,
                 1 if error else 0, 1 if error else 0),
            )
        elif error:
            self._conn.execute(
                """UPDATE sync_log
                   SET last_fetch = ?, error_count = error_count + 1,
                       consecutive_failures = consecutive_failures + 1
                   WHERE feed_name = ?""",
                (now, feed_name),
            )
        else:
            self._conn.execute(
                """UPDATE sync_log
                   SET last_fetch = ?, last_item_date = ?,
                       fetch_count = fetch_count + 1, consecutive_failures = 0
                   WHERE feed_name = ?""",
                (now, last_item_date or existing["last_item_date"], feed_name),
            )
        self._conn.commit()

    def set_cooldown(self, feed_name: str, until: str) -> None:
        self._conn.execute(
            "UPDATE sync_log SET cooldown_until = ? WHERE feed_name = ?",
            (until, feed_name),
        )
        self._conn.commit()

    def get_all_sync_info(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM sync_log ORDER BY feed_name"
        ).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        self._conn.close()
