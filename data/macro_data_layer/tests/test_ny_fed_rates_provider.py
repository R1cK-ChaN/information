"""NY Fed rates provider tests (offline, mocked urlopen)."""

from __future__ import annotations

import io
import json
from contextlib import contextmanager

import pandas as pd
import pytest

from src.providers.ny_fed_rates import NYFedRatesProvider


_FIXTURES = {
    "SOFR": {
        "refRates": [
            {"effectiveDate": "2024-11-14", "type": "SOFR", "percentRate": 4.58, "volumeInBillions": 2295},
            {"effectiveDate": "2024-11-15", "type": "SOFR", "percentRate": 4.60, "volumeInBillions": 2310},
        ]
    },
    "EFFR": {
        "refRates": [
            {"effectiveDate": "2024-11-14", "type": "EFFR", "percentRate": 4.83},
            {"effectiveDate": "2024-11-15", "type": "EFFR", "percentRate": 4.82},
        ]
    },
    "OBFR": {
        "refRates": [
            {"effectiveDate": "2024-11-14", "type": "OBFR", "percentRate": 4.82},
        ]
    },
}


def _mock_urlopen_factory(fixtures: dict[str, dict]):
    @contextmanager
    def fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        for sid, payload in fixtures.items():
            if sid.lower() in url.lower():
                yield io.BytesIO(json.dumps(payload).encode("utf-8"))
                return
        raise AssertionError(f"unexpected URL {url}")
    return fake_urlopen


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(
        "src.providers.ny_fed_rates.urllib.request.urlopen",
        _mock_urlopen_factory(_FIXTURES),
    )
    return NYFedRatesProvider()


@pytest.mark.parametrize("sid", ["SOFR", "EFFR", "OBFR"])
def test_fetch_series_shape(provider, sid):
    df = provider.fetch_series(sid, start="2024-11-01", end="2024-11-30")
    assert isinstance(df, pd.DataFrame)
    assert set(df.columns) == {"date", "value", "source", "series_id"}
    assert df["source"].iloc[0] == "NY_FED"
    assert df["series_id"].iloc[0] == sid
    assert len(df) == len(_FIXTURES[sid]["refRates"])


def test_sort_order(provider):
    df = provider.fetch_series("SOFR", start="2024-11-01", end="2024-11-30")
    assert df["date"].is_monotonic_increasing


def test_unknown_series_raises(provider):
    with pytest.raises(ValueError, match="Unknown NY Fed rate"):
        provider.fetch_series("TBILL")


def test_supports():
    p = NYFedRatesProvider()
    assert p.supports("SOFR", "US") is True
    assert p.supports("sofr", "US") is True
    assert p.supports("SOFR", "GB") is False
    assert p.supports("CPI", "US") is False


def test_empty_response(monkeypatch):
    monkeypatch.setattr(
        "src.providers.ny_fed_rates.urllib.request.urlopen",
        _mock_urlopen_factory({"SOFR": {"refRates": []}}),
    )
    p = NYFedRatesProvider()
    df = p.fetch_series("SOFR", start="2099-01-01", end="2099-01-02")
    assert df.empty
    assert set(df.columns) == {"date", "value", "source", "series_id"}
