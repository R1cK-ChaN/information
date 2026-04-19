"""VIX regime classifier — boundary tests."""

from __future__ import annotations

import pandas as pd
import pytest

from src.storage import Storage
from src.vix_regime import classify_vix_regime


class TestClassifier:
    @pytest.mark.parametrize("value,expected", [
        (5.0, "low"),
        (14.99, "low"),
        (15.0, "elevated"),
        (20.0, "elevated"),
        (24.99, "elevated"),
        (25.0, "stressed"),
        (40.0, "stressed"),
        (80.0, "stressed"),
    ])
    def test_boundaries(self, value, expected):
        assert classify_vix_regime(value) == expected

    def test_none_in_none_out(self):
        assert classify_vix_regime(None) is None


class TestStorageRegimeColumn:
    def test_fresh_storage_has_regime_column(self, tmp_path):
        s = Storage(tmp_path / "m.db")
        cols = {row[1] for row in s.conn.execute("PRAGMA table_info(macro_series)")}
        assert "regime" in cols
        s.close()

    def test_update_regime_round_trip(self, tmp_path):
        s = Storage(tmp_path / "m.db")
        df = pd.DataFrame([
            {"date": pd.Timestamp("2024-11-14"), "value": 12.5,
             "source": "FRED", "series_id": "VIXCLS"},
            {"date": pd.Timestamp("2024-11-15"), "value": 27.0,
             "source": "FRED", "series_id": "VIXCLS"},
        ])
        s.upsert_series("VIX:US", df)
        s.update_regime("VIX:US", [
            ("2024-11-14", "low"),
            ("2024-11-15", "stressed"),
        ])
        rows = s.conn.execute(
            "SELECT date, regime FROM macro_series WHERE series_key='VIX:US' ORDER BY date"
        ).fetchall()
        assert rows == [("2024-11-14", "low"), ("2024-11-15", "stressed")]
        s.close()

    def test_migrates_existing_db_without_regime_column(self, tmp_path):
        """A macro_data.db written before this change must get the column via
        the ALTER TABLE path in Storage._create_tables."""
        import sqlite3
        db = tmp_path / "legacy.db"
        conn = sqlite3.connect(str(db))
        conn.executescript("""
            CREATE TABLE macro_series (
                series_key TEXT NOT NULL, date TEXT NOT NULL, value REAL,
                source TEXT NOT NULL, series_id TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (series_key, date)
            );
        """)
        conn.commit()
        conn.close()

        s = Storage(db)
        cols = {row[1] for row in s.conn.execute("PRAGMA table_info(macro_series)")}
        assert "regime" in cols
        s.close()
