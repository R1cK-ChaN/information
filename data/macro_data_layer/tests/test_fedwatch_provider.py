"""FedWatch provider tests (offline, mocked urlopen)."""

from __future__ import annotations

import io
import json
from contextlib import contextmanager

import pytest

from src.providers.fedwatch import FedWatchProvider
from src.storage import Storage


_FIXTURE = {
    "today": {
        "as_of": "2026-04-19",
        "current band": "3.50 - 3.75",
        "midpoint": 3.625,
        "most_recent_effr": 3.64,
        "rows": [
            {"meeting_iso": "2026-04-29", "implied_rate_post_meeting": 3.63,
             "prob_move_pct": 2.0, "prob_is_cut": False, "change_bps": 0.5},
            {"meeting_iso": "2026-06-17", "implied_rate_post_meeting": 3.618,
             "prob_move_pct": 4.62, "prob_is_cut": True, "change_bps": -0.7},
            {"meeting_iso": "2026-07-29", "implied_rate_post_meeting": 3.585,
             "prob_move_pct": 13.38, "prob_is_cut": True, "change_bps": -4.0},
        ],
    }
}


@contextmanager
def _fake_urlopen(req, timeout=None):
    yield io.BytesIO(json.dumps(_FIXTURE).encode("utf-8"))


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(
        "src.providers.fedwatch.urllib.request.urlopen", _fake_urlopen
    )
    return FedWatchProvider()


class TestFetchLatest:
    def test_snapshot_shape(self, provider):
        snap = provider.fetch_latest()
        assert snap.snapshot_date == "2026-04-19"
        assert snap.midpoint == pytest.approx(3.625)
        assert snap.current_band == "3.50 - 3.75"
        assert len(snap.rows) == 3

    def test_rows_carry_probability_and_direction(self, provider):
        snap = provider.fetch_latest()
        first_cut = snap.rows[1]
        assert first_cut.meeting_date == "2026-06-17"
        assert first_cut.prob_is_cut is True
        assert first_cut.change_bps == pytest.approx(-0.7)

    def test_skips_rows_without_meeting_iso(self, monkeypatch):
        payload = {"today": {"as_of": "2026-04-19", "midpoint": 3.6, "rows": [
            {"implied_rate_post_meeting": 3.6},  # missing meeting_iso — drop
            {"meeting_iso": "2026-04-29", "implied_rate_post_meeting": 3.6},
        ]}}
        @contextmanager
        def fake(req, timeout=None):
            yield io.BytesIO(json.dumps(payload).encode("utf-8"))
        monkeypatch.setattr(
            "src.providers.fedwatch.urllib.request.urlopen", fake
        )
        snap = FedWatchProvider().fetch_latest()
        assert len(snap.rows) == 1


class TestStorageRoundTrip:
    def test_upsert_and_read(self, tmp_path):
        s = Storage(tmp_path / "m.db")
        s.upsert_fedwatch_snapshot("2026-04-19", [
            ("2026-04-29", 3.63, 2.0, False, 0.5),
            ("2026-06-17", 3.618, 4.62, True, -0.7),
        ])
        rows = s.read_fedwatch_snapshot("2026-04-19")
        assert len(rows) == 2
        assert rows[0] == {
            "meeting_date": "2026-04-29",
            "implied_rate": 3.63,
            "prob_move_pct": 2.0,
            "prob_is_cut": False,
            "change_bps": 0.5,
        }
        assert rows[1]["prob_is_cut"] is True
        s.close()

    def test_refresh_fedwatch_end_to_end(self, tmp_path, monkeypatch):
        """MacroDataLayer.refresh_fedwatch persists both the snapshot table
        and the FEDWATCH_MIDPOINT macro_series row."""
        import yaml
        db_path = tmp_path / "macro.db"
        cfg = {
            "storage": {"sqlite_path": str(db_path)},
            "providers": {"fred": {"api_key_env": "FRED_API_KEY"}},
            "ttl": {},
        }
        cfg_path = tmp_path / "cfg.yaml"
        cfg_path.write_text(yaml.safe_dump(cfg))
        monkeypatch.setenv("FRED_API_KEY", "fake")

        from src.data_layer import MacroDataLayer
        from src.providers import fedwatch as fw_mod

        dl = MacroDataLayer(config_path=cfg_path)

        @contextmanager
        def fake(req, timeout=None):
            yield io.BytesIO(json.dumps(_FIXTURE).encode("utf-8"))
        monkeypatch.setattr(fw_mod.urllib.request, "urlopen", fake)

        out = dl.refresh_fedwatch()
        assert out == {"snapshot_date": "2026-04-19", "meetings": 3}

        rows = dl.storage.read_fedwatch_snapshot("2026-04-19")
        assert len(rows) == 3

        ms = dl.storage.conn.execute(
            "SELECT value FROM macro_series WHERE series_key='FEDWATCH_MIDPOINT:US'"
        ).fetchone()
        assert ms is not None
        assert ms[0] == pytest.approx(3.625)
        dl.close()

    def test_reupsert_replaces_meetings_for_same_snapshot(self, tmp_path):
        s = Storage(tmp_path / "m.db")
        s.upsert_fedwatch_snapshot("2026-04-19", [
            ("2026-04-29", 3.63, 2.0, False, 0.5),
            ("2026-06-17", 3.60, 5.0, True, -1.0),
        ])
        # Second snapshot on the same day has only one row — old rows cleared.
        s.upsert_fedwatch_snapshot("2026-04-19", [
            ("2026-04-29", 3.65, 3.0, False, 1.0),
        ])
        rows = s.read_fedwatch_snapshot("2026-04-19")
        assert len(rows) == 1
        assert rows[0]["implied_rate"] == pytest.approx(3.65)
        s.close()
