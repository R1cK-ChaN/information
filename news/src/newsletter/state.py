"""SQLite-backed tracker for already-processed newsletter emails.

Keeps the newsletter ingestor idempotent across refresher ticks. Separate
from the main catalog because the unit of dedup is an *email*, not a
*news item* — one email produces many news_items rows.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path


class NewsletterState:
    """Tracks which emails have already been processed.

    Schema::

        processed_emails(
            dedup_key TEXT PRIMARY KEY,
            sender    TEXT,
            subject   TEXT,
            date      TEXT,
            processed_at INTEGER
        )
    """

    def __init__(self, db_path: str | Path):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_emails (
                dedup_key    TEXT PRIMARY KEY,
                sender       TEXT NOT NULL,
                subject      TEXT NOT NULL,
                date         TEXT NOT NULL,
                processed_at INTEGER NOT NULL
            )
            """
        )
        self._conn.commit()

    def has(self, dedup_key: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM processed_emails WHERE dedup_key = ? LIMIT 1",
            (dedup_key,),
        )
        return cur.fetchone() is not None

    def record(
        self, dedup_key: str, sender: str, subject: str, date_iso: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT OR IGNORE INTO processed_emails
            (dedup_key, sender, subject, date, processed_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (dedup_key, sender, subject, date_iso, int(time.time())),
        )
        self._conn.commit()

    def count(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) FROM processed_emails")
        return cur.fetchone()[0]

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
