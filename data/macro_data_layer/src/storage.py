"""SQLite storage layer for macro time-series data."""

import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS macro_series (
    series_key  TEXT NOT NULL,
    date        TEXT NOT NULL,
    value       REAL,
    source      TEXT NOT NULL,
    series_id   TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (series_key, date)
);
CREATE INDEX IF NOT EXISTS idx_macro_key_date ON macro_series(series_key, date);

CREATE TABLE IF NOT EXISTS alfred_vintages (
    series_id       TEXT NOT NULL,
    date            TEXT NOT NULL,
    realtime_start  TEXT NOT NULL,
    value           REAL,
    PRIMARY KEY (series_id, date, realtime_start)
);
CREATE INDEX IF NOT EXISTS idx_alfred_lookup
    ON alfred_vintages(series_id, date, realtime_start);

CREATE TABLE IF NOT EXISTS sync_log (
    series_key      TEXT PRIMARY KEY,
    last_local_date TEXT,
    last_refresh    TEXT,
    refresh_count   INTEGER DEFAULT 0,
    error_count     INTEGER DEFAULT 0
);
"""


class Storage:
    """SQLite-backed storage for macro economic time-series."""

    def __init__(self, db_path: str | Path = ":memory:"):
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    def upsert_series(self, series_key: str, df: pd.DataFrame) -> int:
        """Insert or replace rows into macro_series from a DataFrame.

        DataFrame must have columns: date, value, source, series_id.
        Returns number of rows upserted.
        """
        now = datetime.now(timezone.utc).isoformat()
        rows = []
        for _, row in df.iterrows():
            date_str = str(row["date"])[:10]  # ensure YYYY-MM-DD
            rows.append((
                series_key,
                date_str,
                row["value"] if pd.notna(row["value"]) else None,
                row["source"],
                row["series_id"],
                now,
            ))
        self.conn.executemany(
            """INSERT OR REPLACE INTO macro_series
               (series_key, date, value, source, series_id, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            rows,
        )
        self.conn.commit()
        return len(rows)

    def read_series(
        self, series_key: str, start: str | None = None, end: str | None = None
    ) -> pd.DataFrame:
        """Query macro_series with optional date range filters."""
        query = "SELECT date, value, source, series_id FROM macro_series WHERE series_key = ?"
        params: list = [series_key]
        if start:
            query += " AND date >= ?"
            params.append(start)
        if end:
            query += " AND date <= ?"
            params.append(end)
        query += " ORDER BY date"
        df = pd.read_sql_query(query, self.conn, params=params)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
        return df

    def get_last_date(self, series_key: str) -> str | None:
        """Return the most recent date stored for a series, or None."""
        cur = self.conn.execute(
            "SELECT MAX(date) FROM macro_series WHERE series_key = ?",
            (series_key,),
        )
        row = cur.fetchone()
        return row[0] if row and row[0] else None

    def upsert_vintages(self, series_id: str, df: pd.DataFrame) -> int:
        """Insert ALFRED vintages, ignoring duplicates.

        DataFrame must have columns: series_id, date, realtime_start, value.
        """
        rows = []
        for _, row in df.iterrows():
            rows.append((
                series_id,
                str(row["date"])[:10],
                str(row["realtime_start"])[:10],
                row["value"] if pd.notna(row["value"]) else None,
            ))
        self.conn.executemany(
            """INSERT OR IGNORE INTO alfred_vintages
               (series_id, date, realtime_start, value)
               VALUES (?, ?, ?, ?)""",
            rows,
        )
        self.conn.commit()
        return len(rows)

    def read_vintage(self, series_id: str, as_of: str) -> pd.DataFrame:
        """Point-in-time query: what was known as of a given date.

        For each observation date, returns the value from the latest vintage
        where realtime_start <= as_of.
        """
        query = """
            SELECT date, value, realtime_start
            FROM alfred_vintages
            WHERE series_id = ?
              AND realtime_start <= ?
              AND (series_id, date, realtime_start) IN (
                  SELECT series_id, date, MAX(realtime_start)
                  FROM alfred_vintages
                  WHERE series_id = ? AND realtime_start <= ?
                  GROUP BY series_id, date
              )
            ORDER BY date
        """
        df = pd.read_sql_query(query, self.conn, params=(series_id, as_of, series_id, as_of))
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
        return df

    def read_all_vintages(self, series_id: str) -> pd.DataFrame:
        """Full revision history for a series."""
        query = """
            SELECT date, realtime_start, value
            FROM alfred_vintages
            WHERE series_id = ?
            ORDER BY date, realtime_start
        """
        df = pd.read_sql_query(query, self.conn, params=(series_id,))
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            df["realtime_start"] = pd.to_datetime(df["realtime_start"])
        return df

    def get_sync_info(self, series_key: str) -> dict | None:
        """Read sync_log entry for a series. Returns None if not found."""
        cur = self.conn.execute(
            "SELECT last_local_date, last_refresh, refresh_count, error_count "
            "FROM sync_log WHERE series_key = ?",
            (series_key,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "last_local_date": row[0],
            "last_refresh": row[1],
            "refresh_count": row[2],
            "error_count": row[3],
        }

    def update_sync(self, series_key: str, last_date: str | None = None, error: bool = False):
        """Update sync_log after a refresh attempt."""
        now = datetime.now(timezone.utc).isoformat()
        existing = self.get_sync_info(series_key)
        if existing is None:
            self.conn.execute(
                """INSERT INTO sync_log (series_key, last_local_date, last_refresh, refresh_count, error_count)
                   VALUES (?, ?, ?, 1, ?)""",
                (series_key, last_date, now, 1 if error else 0),
            )
        else:
            if error:
                self.conn.execute(
                    "UPDATE sync_log SET last_refresh = ?, error_count = error_count + 1 WHERE series_key = ?",
                    (now, series_key),
                )
            else:
                self.conn.execute(
                    """UPDATE sync_log SET last_local_date = ?, last_refresh = ?,
                       refresh_count = refresh_count + 1 WHERE series_key = ?""",
                    (last_date or existing["last_local_date"], now, series_key),
                )
        self.conn.commit()

    def close(self):
        """Close the SQLite connection."""
        self.conn.close()
