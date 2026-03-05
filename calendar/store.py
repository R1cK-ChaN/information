"""
store.py — SQLite storage for economic calendar events.
"""

import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "calendar.db"


def _conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = _conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS calendar_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT UNIQUE,
            datetime_utc TEXT NOT NULL,
            country TEXT NOT NULL,
            indicator TEXT NOT NULL,
            category TEXT,
            importance TEXT,
            actual TEXT,
            forecast TEXT,
            previous TEXT,
            surprise REAL,
            scraped_at TEXT NOT NULL,
            raw_json TEXT
        )
    """)
    conn.commit()
    conn.close()


def upsert_event(event: dict):
    conn = _conn()
    now = datetime.now(timezone.utc).isoformat()

    surprise = None
    try:
        if event.get("actual") and event.get("forecast"):
            strip = lambda s: float(str(s).replace("%", "").replace("K", "").replace("M", "").replace("B", "").replace(",", "").strip())
            surprise = round(strip(event["actual"]) - strip(event["forecast"]), 4)
    except (ValueError, TypeError):
        pass

    conn.execute("""
        INSERT INTO calendar_events
            (event_id, datetime_utc, country, indicator, category,
             importance, actual, forecast, previous, surprise,
             scraped_at, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(event_id) DO UPDATE SET
            actual    = excluded.actual,
            forecast  = excluded.forecast,
            previous  = excluded.previous,
            surprise  = excluded.surprise,
            scraped_at = excluded.scraped_at,
            raw_json  = excluded.raw_json
    """, (
        event["event_id"],
        event["datetime_utc"],
        event["country"],
        event["indicator"],
        event.get("category", ""),
        event.get("importance", ""),
        event.get("actual"),
        event.get("forecast"),
        event.get("previous"),
        surprise,
        now,
        json.dumps(event),
    ))
    conn.commit()
    conn.close()


def get_events(date: str = None, country: str = None, importance: str = None):
    """Query stored events. All filters are optional."""
    conn = _conn()
    clauses, params = [], []

    if date:
        clauses.append("datetime_utc LIKE ?")
        params.append(f"{date}%")
    if country:
        clauses.append("country = ?")
        params.append(country)
    if importance:
        clauses.append("importance = ?")
        params.append(importance)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM calendar_events {where} ORDER BY datetime_utc ASC",
        params,
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_surprises(days: int = 7, min_importance: str = "high"):
    conn = _conn()
    rows = conn.execute("""
        SELECT * FROM calendar_events
        WHERE surprise IS NOT NULL
          AND importance = ?
          AND datetime_utc >= datetime('now', ?)
        ORDER BY ABS(surprise) DESC
    """, (min_importance, f"-{days} days")).fetchall()
    conn.close()
    return [dict(r) for r in rows]
