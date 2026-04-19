"""Cross-source subject-scoped item query.

For a given canonical subject id, return a merged list of items from:
  1. the shared catalog (news, newsletter, gov_report, doc_parser) via
     ``item_subjects`` tagged at ingest
  2. calendar.db via ``calendar_indicator`` aliases
  3. macro_data.db via ``fred_series`` aliases

Calendar and macro rows are normalised into the same shape as catalog rows
so the API can return one uniform list.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# Per-source caps prevent a freshly-synced external DB (e.g. a macro bulk
# import) from flooding the merged result and pushing every news/calendar row
# past the final `limit`. The final merge still honours `limit` overall.
_CALENDAR_CAP = 20
_MACRO_CAP = 10


def query_by_subject(
    catalog,
    subject_id: str,
    *,
    calendar_db_path: Path | None = None,
    macro_db_path: Path | None = None,
    min_confidence: float = 0.0,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Merge results from catalog, calendar, and macro_data for a subject.

    Returns a list of normalised item dicts sorted by date desc (best-effort).
    Per-source caps bound how many rows each external DB can contribute so a
    bulk macro sync can't push catalog/calendar rows out of the response.
    """
    aliases = _fetch_aliases(catalog, subject_id)
    if not aliases and not catalog.get_aliases(subject_id):
        return []

    items: list[dict[str, Any]] = []
    items.extend(_from_catalog(catalog, subject_id, min_confidence, limit))

    if calendar_db_path and calendar_db_path.exists():
        cal_aliases = aliases.get("calendar_indicator", [])
        if cal_aliases:
            items.extend(_from_calendar(
                calendar_db_path, subject_id, cal_aliases,
                min(_CALENDAR_CAP, limit),
            ))

    if macro_db_path and macro_db_path.exists():
        fred_aliases = aliases.get("fred_series", [])
        if fred_aliases:
            items.extend(_from_macro(
                macro_db_path, subject_id, fred_aliases,
                min(_MACRO_CAP, limit),
            ))

    items.sort(key=_sort_key, reverse=True)
    return items[:limit]


# ── helpers ────────────────────────────────────────────────────────────────


def _fetch_aliases(catalog, subject_id: str) -> dict[str, list[str]]:
    rows = catalog._conn.execute(
        """SELECT alias_type, alias_value FROM subject_aliases
           WHERE subject_id = ?""",
        (subject_id,),
    ).fetchall()
    grouped: dict[str, list[str]] = {}
    for atype, aval in rows:
        grouped.setdefault(atype, []).append(aval)
    return grouped


def _from_catalog(
    catalog, subject_id: str, min_confidence: float, limit: int
) -> list[dict]:
    rows = catalog.get_items_by_subject(
        subject_id, min_confidence=min_confidence, limit=limit
    )
    out = []
    for r in rows:
        r["subject_id"] = subject_id
        out.append(r)
    return out


def _from_calendar(
    db_path: Path, subject_id: str, indicators: list[str], limit: int
) -> list[dict]:
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        placeholders = ",".join("?" for _ in indicators)
        rows = conn.execute(
            f"""SELECT * FROM calendar_events
                WHERE indicator IN ({placeholders})
                ORDER BY datetime_utc DESC LIMIT ?""",
            (*indicators, limit),
        ).fetchall()
        conn.close()
    except sqlite3.Error as exc:
        logger.warning("calendar query failed: %s", exc)
        return []

    out = []
    for r in rows:
        rd = dict(r)
        actual = rd.get("actual")
        forecast = rd.get("forecast")
        title_bits = [rd["indicator"]]
        if actual:
            title_bits.append(f"actual={actual}")
        if forecast:
            title_bits.append(f"forecast={forecast}")
        synthetic_sha = hashlib.sha256(
            f"calendar:{rd['event_id']}".encode()
        ).hexdigest()
        out.append({
            "sha256": synthetic_sha,
            "source": "calendar",
            "title": " ".join(title_bits),
            "country": rd.get("country"),
            "publish_date": (rd.get("datetime_utc") or "")[:10],
            "processed_at": _parse_iso_epoch(rd.get("datetime_utc")),
            "impact_level": rd.get("importance"),
            "subject_id": subject_id,
            "subject_confidence": 1.0,
            "raw": rd,
        })
    return out


def _from_macro(
    db_path: Path, subject_id: str, series_ids: list[str], limit: int
) -> list[dict]:
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        placeholders = ",".join("?" for _ in series_ids)
        rows = conn.execute(
            f"""SELECT series_key, date, value, source, series_id, updated_at
                FROM macro_series
                WHERE series_id IN ({placeholders})
                ORDER BY date DESC LIMIT ?""",
            (*series_ids, limit),
        ).fetchall()
        conn.close()
    except sqlite3.Error as exc:
        logger.warning("macro_data query failed: %s", exc)
        return []

    out = []
    for r in rows:
        rd = dict(r)
        synthetic_sha = hashlib.sha256(
            f"macro:{rd['series_key']}:{rd['date']}".encode()
        ).hexdigest()
        out.append({
            "sha256": synthetic_sha,
            "source": "macro_data",
            "title": f"{rd['series_id']}: {rd['value']}",
            "publish_date": rd["date"],
            # Sort by observation date, not ingest time, so a fresh macro sync
            # doesn't promote years-old prints above today's news.
            "processed_at": _parse_iso_epoch(rd["date"]),
            "institution": rd.get("source"),
            "subject_id": subject_id,
            "subject_confidence": 1.0,
            "raw": rd,
        })
    return out


def _parse_iso_epoch(val: str | None) -> int:
    if not val:
        return 0
    try:
        from datetime import datetime
        return int(datetime.fromisoformat(val.replace("Z", "+00:00")).timestamp())
    except (ValueError, TypeError):
        return 0


def _sort_key(item: dict) -> tuple[int, str]:
    return (item.get("processed_at") or 0, item.get("publish_date") or "")
