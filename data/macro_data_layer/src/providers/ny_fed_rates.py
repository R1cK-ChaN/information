"""NY Fed reference rates provider (SOFR, EFFR, OBFR).

Uses the NY Fed Markets Data API (public, no auth required):
  SOFR: /api/rates/secured/sofr/search.json
  EFFR: /api/rates/unsecured/effr/search.json
  OBFR: /api/rates/unsecured/obfr/search.json
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from typing import Any

import pandas as pd

from .base import BaseProvider

logger = logging.getLogger(__name__)

_BASE = "https://markets.newyorkfed.org/api/rates"
_PATHS = {
    "SOFR": "secured/sofr/search.json",
    "EFFR": "unsecured/effr/search.json",
    "OBFR": "unsecured/obfr/search.json",
}
_SUPPORTED = set(_PATHS)


class NYFedRatesProvider(BaseProvider):
    """Provider for NY Fed reference rates (SOFR / EFFR / OBFR)."""

    provider_name = "NY_FED"

    def __init__(self, timeout: float = 30.0) -> None:
        self.timeout = timeout

    def _fetch_json(self, url: str) -> dict[str, Any]:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def fetch_series(
        self,
        series_id: str,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        """Fetch a NY Fed rate series. Returns DataFrame with columns: date, value, source, series_id.

        Args:
            series_id: One of "SOFR", "EFFR", "OBFR".
            start: Observation start "YYYY-MM-DD". Required by the API — defaults to 2014-01-01
                (SOFR inception is 2018; EFFR/OBFR go back further but this keeps the request bounded).
            end: Observation end "YYYY-MM-DD". Defaults to today.
        """
        sid = series_id.upper()
        if sid not in _PATHS:
            raise ValueError(f"Unknown NY Fed rate '{series_id}'. Expected one of {sorted(_SUPPORTED)}")

        params = {
            "startDate": start or "2014-01-01",
            "endDate": end or pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d"),
        }
        url = f"{_BASE}/{_PATHS[sid]}?{urllib.parse.urlencode(params)}"
        payload = self._fetch_json(url)

        records = payload.get("refRates") or []
        if not records:
            return pd.DataFrame(columns=["date", "value", "source", "series_id"])

        df = pd.DataFrame([
            {
                "date": pd.to_datetime(r["effectiveDate"]),
                "value": r.get("percentRate"),
            }
            for r in records
            if r.get("effectiveDate") is not None
        ])
        df["source"] = self.provider_name
        df["series_id"] = sid
        df = df.sort_values("date").reset_index(drop=True)
        return df[["date", "value", "source", "series_id"]]

    def supports(self, indicator: str, country: str) -> bool:
        return country == "US" and indicator.upper() in _SUPPORTED
