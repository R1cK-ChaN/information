"""Integration test for the cross-source subject query.

Seeds one item per source and asserts that querying by subject returns
all of them. This is the acceptance-criteria test for issue #2.
"""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

import pytest

# Make `src.api.subject_query` importable without installing the news package.
_NEWS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_NEWS))
sys.path.insert(0, str(_NEWS.parent))  # repo root for `widgets`

from src.api.subject_query import query_by_subject
from widgets.catalog import Catalog
from widgets.subjects_loader import sync_from_yaml
from widgets.tagger import SubjectTagger


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SEED_YAML = REPO_ROOT / "config" / "subjects.yaml"


@pytest.fixture
def seeded_env(tmp_path):
    """Build a catalog + calendar.db + macro_data.db seeded with CPI items."""
    catalog_path = tmp_path / "catalog.db"
    calendar_path = tmp_path / "calendar.db"
    macro_path = tmp_path / "macro.db"

    catalog = Catalog(catalog_path)
    sync_from_yaml(catalog, SEED_YAML)
    tagger = SubjectTagger(catalog)
    catalog.tagger = tagger

    now = int(time.time())

    # --- Catalog: news + newsletter + gov_report rows, all CPI-tagged ---
    # In production, newsletter items flow through the same `convert_item`
    # helper as RSS news and land with source="news" (see
    # news/src/common/export.py:110). We reproduce that here rather than
    # invent a "newsletter" source that never appears in the catalog.
    # The test still demonstrates cross-source merging because distinct
    # source prefixes (news / gov_report:* / calendar / macro_data) land
    # in the result.
    for sha, source, title, ts in [
        ("a" * 64, "news", "US CPI ticks up to 3.2% in June", now),
        ("b" * 64, "news", "Deep dive: what the CPI print means (newsletter)", now - 10),
        ("c" * 64, "gov_report:us_bls", "BLS CPI Release — June 2025", now - 20),
    ]:
        result = {
            "sha256": sha,
            "source": source,
            "title": title,
            "processed_at": ts,
        }
        subjects = tagger.tag_text(title)
        catalog.insert(result, f"/tmp/{sha}.json", subjects=subjects)

    # --- calendar.db ---
    cal = sqlite3.connect(str(calendar_path))
    cal.execute("""
        CREATE TABLE calendar_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT UNIQUE, datetime_utc TEXT NOT NULL,
            country TEXT NOT NULL, indicator TEXT NOT NULL,
            category TEXT, importance TEXT,
            actual TEXT, forecast TEXT, previous TEXT, surprise REAL,
            scraped_at TEXT NOT NULL, raw_json TEXT
        )""")
    cal.execute(
        """INSERT INTO calendar_events
           (event_id, datetime_utc, country, indicator, category, importance,
            actual, forecast, previous, surprise, scraped_at, raw_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("us_cpi_jun25", "2025-06-12T12:30:00+00:00", "US", "CPI",
         "Inflation", "high", "3.2%", "3.1%", "3.0%", 0.1,
         "2025-06-12T12:31:00+00:00", "{}"),
    )
    cal.commit()
    cal.close()

    # --- macro_data.db ---
    mac = sqlite3.connect(str(macro_path))
    mac.execute("""
        CREATE TABLE macro_series (
            series_key TEXT NOT NULL, date TEXT NOT NULL, value REAL,
            source TEXT NOT NULL, series_id TEXT NOT NULL, updated_at TEXT NOT NULL,
            PRIMARY KEY (series_key, date)
        )""")
    mac.execute(
        """INSERT INTO macro_series VALUES (?,?,?,?,?,?)""",
        ("CPI:US", "2025-06-12", 321.5, "FRED", "CPIAUCSL",
         "2025-06-12T12:35:00+00:00"),
    )
    mac.commit()
    mac.close()

    yield catalog, calendar_path, macro_path
    catalog.close()


class TestQueryBySubject:
    def test_returns_all_cross_source_rows_for_cpi(self, seeded_env):
        catalog, cal_path, mac_path = seeded_env
        items = query_by_subject(
            catalog, "econ.cpi",
            calendar_db_path=cal_path,
            macro_db_path=mac_path,
        )
        sources = {it["source"] for it in items}
        # news (covers both RSS and newsletter production paths),
        # gov_report:us_bls, calendar, macro_data — 4 distinct source kinds.
        assert "news" in sources
        assert any(s.startswith("gov_report") for s in sources)
        assert "calendar" in sources
        assert "macro_data" in sources
        assert len(items) == 5

    def test_structured_sources_have_confidence_1(self, seeded_env):
        catalog, cal_path, mac_path = seeded_env
        items = query_by_subject(
            catalog, "econ.cpi",
            calendar_db_path=cal_path, macro_db_path=mac_path,
        )
        for it in items:
            if it["source"] in ("calendar", "macro_data"):
                assert it["subject_confidence"] == 1.0

    def test_catalog_only_when_external_dbs_missing(self, seeded_env):
        catalog, _, _ = seeded_env
        items = query_by_subject(catalog, "econ.cpi")
        # No external dbs → only the 3 catalog rows.
        assert len(items) == 3
        assert all(it["source"] != "calendar" for it in items)
        assert all(it["source"] != "macro_data" for it in items)

    def test_unknown_subject_returns_empty(self, seeded_env):
        catalog, cal_path, mac_path = seeded_env
        items = query_by_subject(
            catalog, "econ.does.not.exist",
            calendar_db_path=cal_path, macro_db_path=mac_path,
        )
        assert items == []

    def test_min_confidence_filters_news(self, seeded_env):
        catalog, cal_path, mac_path = seeded_env
        # Catalog rows were tagged at confidence 0.8 (title regex).
        items = query_by_subject(
            catalog, "econ.cpi",
            calendar_db_path=cal_path, macro_db_path=mac_path,
            min_confidence=0.9,
        )
        # 0.9 threshold drops the three 0.8 catalog rows, keeps calendar + macro.
        sources = {it["source"] for it in items}
        assert sources == {"calendar", "macro_data"}

    def test_limit_is_respected(self, seeded_env):
        catalog, cal_path, mac_path = seeded_env
        items = query_by_subject(
            catalog, "econ.cpi",
            calendar_db_path=cal_path, macro_db_path=mac_path,
            limit=2,
        )
        assert len(items) == 2


class TestNyFedSeriesAliases:
    """rate.us.sofr / effr / obfr use the ny_fed_series alias type; verify the
    macro query surfaces rows stored with source='NY_FED'."""

    def test_fedwatch_midpoint_routed_via_fedwatch_series(self, tmp_path):
        catalog_path = tmp_path / "catalog.db"
        macro_path = tmp_path / "macro.db"

        catalog = Catalog(catalog_path)
        sync_from_yaml(catalog, SEED_YAML)

        mac = sqlite3.connect(str(macro_path))
        mac.execute("""
            CREATE TABLE macro_series (
                series_key TEXT NOT NULL, date TEXT NOT NULL, value REAL,
                source TEXT NOT NULL, series_id TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY (series_key, date)
            )""")
        mac.execute(
            "INSERT INTO macro_series VALUES (?,?,?,?,?,?)",
            ("FEDWATCH_MIDPOINT:US", "2026-04-19", 3.625,
             "RATEPROBABILITY", "FEDWATCH_MIDPOINT",
             "2026-04-19T12:00:00+00:00"),
        )
        mac.commit()
        mac.close()

        items = query_by_subject(
            catalog, "rate.us.fedwatch", macro_db_path=macro_path,
        )
        assert len(items) == 1
        assert items[0]["source"] == "macro_data"
        assert items[0]["raw"]["series_id"] == "FEDWATCH_MIDPOINT"
        catalog.close()

    def test_sofr_macro_row_routed_via_ny_fed_series(self, tmp_path):
        catalog_path = tmp_path / "catalog.db"
        macro_path = tmp_path / "macro.db"

        catalog = Catalog(catalog_path)
        sync_from_yaml(catalog, SEED_YAML)

        mac = sqlite3.connect(str(macro_path))
        mac.execute("""
            CREATE TABLE macro_series (
                series_key TEXT NOT NULL, date TEXT NOT NULL, value REAL,
                source TEXT NOT NULL, series_id TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY (series_key, date)
            )""")
        mac.execute(
            "INSERT INTO macro_series VALUES (?,?,?,?,?,?)",
            ("SOFR:US", "2024-11-15", 4.60, "NY_FED", "SOFR",
             "2024-11-15T12:00:00+00:00"),
        )
        mac.commit()
        mac.close()

        items = query_by_subject(
            catalog, "rate.us.sofr", macro_db_path=macro_path,
        )
        assert len(items) == 1
        assert items[0]["source"] == "macro_data"
        assert items[0]["raw"]["series_id"] == "SOFR"
        catalog.close()
