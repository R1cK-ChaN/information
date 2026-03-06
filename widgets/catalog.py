"""Shared SQLite catalog index for all standardized JSON extractions.

Every package (doc_parser, gov_report, news) writes JSON to a unified
``output/`` folder and registers each item here for fast querying and dedup.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    sha256              TEXT PRIMARY KEY,
    json_path           TEXT,
    source              TEXT,
    title               TEXT,
    institution         TEXT,
    publish_date        TEXT,
    data_period         TEXT,
    country             TEXT,
    market              TEXT,
    asset_class         TEXT,
    sector              TEXT,
    document_type       TEXT,
    event_type          TEXT,
    subject             TEXT,
    subject_id          TEXT,
    language            TEXT,
    contains_commentary INTEGER,
    impact_level        TEXT,
    confidence          REAL,
    processed_at        INTEGER
);
CREATE INDEX IF NOT EXISTS idx_source       ON items(source);
CREATE INDEX IF NOT EXISTS idx_publish_date ON items(publish_date);
CREATE INDEX IF NOT EXISTS idx_impact_level ON items(impact_level);
"""


class Catalog:
    """Shared SQLite catalog for unified output/ folder."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)

    # -- Dedup ---------------------------------------------------------------

    def has(self, sha256: str) -> bool:
        """Return True if *sha256* already exists in the catalog."""
        row = self._conn.execute(
            "SELECT 1 FROM items WHERE sha256 = ?", (sha256,)
        ).fetchone()
        return row is not None

    # -- Write ---------------------------------------------------------------

    def insert(self, result: dict, json_path: str | Path) -> None:
        """Insert a result dict into the catalog.

        *result* must contain a ``sha256`` key.  All 17 entity fields are
        read from the dict (missing keys default to ``None``).
        """
        self._conn.execute(
            """INSERT OR REPLACE INTO items
               (sha256, json_path, source, title, institution, publish_date,
                data_period, country, market, asset_class, sector,
                document_type, event_type, subject, subject_id, language,
                contains_commentary, impact_level, confidence, processed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                result["sha256"],
                str(json_path),
                result.get("source"),
                result.get("title"),
                result.get("institution"),
                result.get("publish_date"),
                result.get("data_period"),
                result.get("country"),
                result.get("market"),
                result.get("asset_class"),
                result.get("sector"),
                result.get("document_type"),
                result.get("event_type"),
                result.get("subject"),
                result.get("subject_id"),
                result.get("language"),
                1 if result.get("contains_commentary") else 0,
                result.get("impact_level"),
                result.get("confidence"),
                result.get("processed_at"),
            ),
        )
        self._conn.commit()

    # -- Read ----------------------------------------------------------------

    def get_latest(
        self,
        n: int = 20,
        *,
        source: str | None = None,
        impact_level: str | None = None,
    ) -> list[dict]:
        """Return the *n* most recent items, optionally filtered."""
        query = "SELECT * FROM items WHERE 1=1"
        params: list[Any] = []
        if source:
            query += " AND source = ?"
            params.append(source)
        if impact_level:
            query += " AND impact_level = ?"
            params.append(impact_level)
        query += " ORDER BY processed_at DESC LIMIT ?"
        params.append(n)
        return [dict(r) for r in self._conn.execute(query, params).fetchall()]

    def search(self, query_str: str, limit: int = 20) -> list[dict]:
        """Full-text LIKE search on title."""
        rows = self._conn.execute(
            "SELECT * FROM items WHERE title LIKE ? ORDER BY processed_at DESC LIMIT ?",
            (f"%{query_str}%", limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_recent_titles(
        self, source: str | None = None, hours: int = 24
    ) -> list[str]:
        """Return titles from the last *hours* for Jaccard dedup seeding."""
        query = "SELECT title FROM items WHERE processed_at >= ?"
        import time

        cutoff = int(time.time()) - hours * 3600
        params: list[Any] = [cutoff]
        if source:
            query += " AND source = ?"
            params.append(source)
        query += " ORDER BY processed_at DESC"
        rows = self._conn.execute(query, params).fetchall()
        return [r["title"] for r in rows if r["title"]]

    def count(self, source: str | None = None) -> int:
        """Total number of cataloged items, optionally filtered by source."""
        if source:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM items WHERE source = ?", (source,)
            ).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) FROM items").fetchone()
        return row[0]

    def remove(self, sha256: str) -> bool:
        """Remove an item from the catalog. Returns True if deleted."""
        cur = self._conn.execute(
            "DELETE FROM items WHERE sha256 = ?", (sha256,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        self._conn.close()
