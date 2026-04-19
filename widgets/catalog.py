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

CREATE TABLE IF NOT EXISTS subjects (
    subject_id   TEXT PRIMARY KEY,
    display_name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS subject_aliases (
    subject_id  TEXT NOT NULL,
    alias_type  TEXT NOT NULL,
    alias_value TEXT NOT NULL,
    PRIMARY KEY (subject_id, alias_type, alias_value)
);
CREATE INDEX IF NOT EXISTS idx_aliases_lookup
    ON subject_aliases(alias_type, alias_value);
CREATE TABLE IF NOT EXISTS item_subjects (
    item_sha   TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    confidence REAL NOT NULL,
    PRIMARY KEY (item_sha, subject_id)
);
CREATE INDEX IF NOT EXISTS idx_item_subjects_subject
    ON item_subjects(subject_id);

CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
    sha256 UNINDEXED,
    title,
    body,
    tokenize = 'porter unicode61'
);
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
        self._backfill_fts_if_empty()

    # -- FTS init ------------------------------------------------------------

    def _backfill_fts_if_empty(self) -> None:
        """Populate ``items_fts`` from ``items.title`` when the FTS index is
        smaller than the catalog. Idempotent: no-op if counts already match.

        Only the title is backfilled — older rows pre-date the ``body_text``
        parameter on ``insert()``, so they have no indexable body.
        """
        fts_n = self._conn.execute("SELECT count(*) FROM items_fts").fetchone()[0]
        items_n = self._conn.execute("SELECT count(*) FROM items").fetchone()[0]
        if fts_n >= items_n:
            return
        with self._conn:
            self._conn.execute("DELETE FROM items_fts")
            self._conn.execute(
                """INSERT INTO items_fts(sha256, title, body)
                   SELECT sha256, COALESCE(title, ''), '' FROM items"""
            )

    # -- Dedup ---------------------------------------------------------------

    def has(self, sha256: str) -> bool:
        """Return True if *sha256* already exists in the catalog."""
        row = self._conn.execute(
            "SELECT 1 FROM items WHERE sha256 = ?", (sha256,)
        ).fetchone()
        return row is not None

    # -- Write ---------------------------------------------------------------

    def insert(
        self,
        result: dict,
        json_path: str | Path,
        *,
        subjects: list[tuple[str, float]] | None = None,
        body_text: str | None = None,
    ) -> None:
        """Insert a result dict into the catalog.

        *result* must contain a ``sha256`` key.  All entity fields are
        read from the dict (missing keys default to ``None``).

        *subjects* is an optional list of ``(subject_id, confidence)`` tuples
        to populate the ``item_subjects`` join table in the same transaction.
        Existing tags for this sha are replaced.

        *body_text* is optional plaintext content indexed by ``items_fts``
        alongside the title for BM25 search. If omitted, only the title is
        searchable for this row.
        """
        with self._conn:
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
            if subjects is not None:
                self._conn.execute(
                    "DELETE FROM item_subjects WHERE item_sha = ?",
                    (result["sha256"],),
                )
                if subjects:
                    self._conn.executemany(
                        """INSERT INTO item_subjects
                           (item_sha, subject_id, confidence)
                           VALUES (?,?,?)""",
                        [(result["sha256"], sid, conf) for sid, conf in subjects],
                    )

            self._conn.execute(
                "DELETE FROM items_fts WHERE sha256 = ?",
                (result["sha256"],),
            )
            self._conn.execute(
                "INSERT INTO items_fts(sha256, title, body) VALUES (?,?,?)",
                (result["sha256"], result.get("title") or "", body_text or ""),
            )

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

    def search_fts(
        self,
        query_str: str,
        *,
        limit: int = 20,
        subject_id: str | None = None,
        min_confidence: float = 0.0,
    ) -> list[dict]:
        """BM25-ranked full-text search across ``title + body`` via FTS5.

        *query_str* is phrase-quoted so arbitrary user text (including
        punctuation or FTS operators) is treated as a literal phrase —
        callers that want AND/OR/NEAR can build the MATCH expression
        themselves and pass it through a dedicated API later.

        *subject_id* optionally intersects the result with the ``item_subjects``
        join table so ``q=`` composes with the existing ``subject=`` filter.
        """
        match_expr = '"' + query_str.replace('"', '""') + '"'
        if subject_id is None:
            rows = self._conn.execute(
                """SELECT items.*, bm25(items_fts) AS fts_rank
                   FROM items_fts
                   JOIN items ON items.sha256 = items_fts.sha256
                   WHERE items_fts MATCH ?
                   ORDER BY fts_rank LIMIT ?""",
                (match_expr, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT items.*, bm25(items_fts) AS fts_rank,
                          item_subjects.confidence AS subject_confidence
                   FROM items_fts
                   JOIN items         ON items.sha256         = items_fts.sha256
                   JOIN item_subjects ON item_subjects.item_sha = items_fts.sha256
                   WHERE items_fts MATCH ?
                     AND item_subjects.subject_id = ?
                     AND item_subjects.confidence >= ?
                   ORDER BY fts_rank LIMIT ?""",
                (match_expr, subject_id, min_confidence, limit),
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
        with self._conn:
            cur = self._conn.execute(
                "DELETE FROM items WHERE sha256 = ?", (sha256,)
            )
            self._conn.execute(
                "DELETE FROM items_fts WHERE sha256 = ?", (sha256,)
            )
        return cur.rowcount > 0

    # -- Subjects ------------------------------------------------------------

    def sync_subjects(
        self,
        subjects: list[dict],
    ) -> None:
        """Sync the subject vocabulary into the catalog.

        *subjects* is the list of dicts parsed from ``config/subjects.yaml``
        (each with ``id``, ``display``, ``aliases``). Replaces any existing
        rows for each subject. Subjects not in the input are left alone —
        deleting subjects is intentionally manual.
        """
        with self._conn:
            for sub in subjects:
                sid = sub["id"]
                self._conn.execute(
                    "INSERT OR REPLACE INTO subjects (subject_id, display_name) VALUES (?, ?)",
                    (sid, sub["display"]),
                )
                self._conn.execute(
                    "DELETE FROM subject_aliases WHERE subject_id = ?",
                    (sid,),
                )
                rows: list[tuple[str, str, str]] = []
                for alias_type, values in (sub.get("aliases") or {}).items():
                    for v in values or []:
                        rows.append((sid, alias_type, v))
                if rows:
                    self._conn.executemany(
                        """INSERT OR IGNORE INTO subject_aliases
                           (subject_id, alias_type, alias_value) VALUES (?,?,?)""",
                        rows,
                    )

    def get_aliases(
        self, subject_id: str, alias_type: str | None = None
    ) -> list[str]:
        """Return alias values for a subject, optionally filtered by type."""
        if alias_type:
            rows = self._conn.execute(
                """SELECT alias_value FROM subject_aliases
                   WHERE subject_id = ? AND alias_type = ?""",
                (subject_id, alias_type),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT alias_value FROM subject_aliases WHERE subject_id = ?",
                (subject_id,),
            ).fetchall()
        return [r[0] for r in rows]

    def get_items_by_subject(
        self,
        subject_id: str,
        *,
        min_confidence: float = 0.0,
        limit: int = 100,
    ) -> list[dict]:
        """Return catalog items tagged with *subject_id*, ordered by recency."""
        rows = self._conn.execute(
            """SELECT items.*, item_subjects.confidence AS subject_confidence
               FROM items
               JOIN item_subjects ON items.sha256 = item_subjects.item_sha
               WHERE item_subjects.subject_id = ?
                 AND item_subjects.confidence >= ?
               ORDER BY items.processed_at DESC
               LIMIT ?""",
            (subject_id, min_confidence, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_subjects(self) -> list[dict]:
        """Return all subjects with their display names."""
        rows = self._conn.execute(
            "SELECT subject_id, display_name FROM subjects ORDER BY subject_id"
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        self._conn.close()
