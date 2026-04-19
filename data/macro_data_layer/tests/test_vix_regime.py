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

    def test_nan_and_inf_treated_as_missing(self):
        # Regression: float NaN used to pass the `is None` check and return
        # "stressed" because NaN < 15 is False and NaN < 25 is False.
        assert classify_vix_regime(float("nan")) is None
        assert classify_vix_regime(float("inf")) is None
        assert classify_vix_regime(float("-inf")) is None
        import pandas as pd
        assert classify_vix_regime(pd.NA) is None if hasattr(pd, "NA") else True


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

    def test_bootstrap_classifies_vix_history(self, tmp_path, monkeypatch):
        """Bootstrap used to insert VIX rows without calling the regime
        classifier, so historical bootstrap rows sat at null until a later
        refresh touched them."""
        import pandas as pd
        import yaml
        db_path = tmp_path / "m.db"
        cfg = {
            "storage": {"sqlite_path": str(db_path)},
            "providers": {"fred": {"api_key_env": "FRED_API_KEY"}},
            "ttl": {},
        }
        cfg_path = tmp_path / "cfg.yaml"
        cfg_path.write_text(yaml.safe_dump(cfg))
        monkeypatch.setenv("FRED_API_KEY", "fake")

        from src.data_layer import MacroDataLayer
        dl = MacroDataLayer(config_path=cfg_path)

        vix_df = pd.DataFrame([
            {"date": pd.Timestamp("2024-01-02"), "value": 12.0,
             "source": "FRED", "series_id": "VIXCLS"},
            {"date": pd.Timestamp("2024-01-03"), "value": 30.0,
             "source": "FRED", "series_id": "VIXCLS"},
        ])
        other_df = pd.DataFrame([
            {"date": pd.Timestamp("2024-01-02"), "value": 321.0,
             "source": "FRED", "series_id": "CPIAUCSL"},
        ])

        def fake_fetch(series_id, start=None, end=None, units=None):
            if series_id == "VIXCLS":
                return vix_df
            return other_df

        def fake_fetch_releases(series_id):
            return pd.DataFrame(columns=["series_id", "date", "realtime_start", "value"])

        monkeypatch.setattr(dl.fred, "fetch_series", fake_fetch)
        monkeypatch.setattr(dl.fred, "fetch_all_releases", fake_fetch_releases)
        monkeypatch.setattr("time.sleep", lambda *_: None)

        dl.bootstrap()

        rows = dl.storage.conn.execute(
            "SELECT date, regime FROM macro_series WHERE series_key='VIX:US' ORDER BY date"
        ).fetchall()
        assert rows == [("2024-01-02", "low"), ("2024-01-03", "stressed")]

        # Non-VIX series must remain untouched.
        cpi = dl.storage.conn.execute(
            "SELECT regime FROM macro_series WHERE series_key='CPI:US'"
        ).fetchone()
        assert cpi[0] is None
        dl.close()

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
