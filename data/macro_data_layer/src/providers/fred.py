"""FRED data provider using fredapi."""

import logging

import pandas as pd
from fredapi import Fred

from .base import BaseProvider

logger = logging.getLogger(__name__)


class FREDProvider(BaseProvider):
    """Provider for FRED (Federal Reserve Economic Data) and ALFRED vintages."""

    provider_name = "FRED"

    def __init__(self, api_key: str):
        self.fred = Fred(api_key=api_key)

    def fetch_series(
        self,
        series_id: str,
        start: str | None = None,
        end: str | None = None,
        units: str | None = None,
    ) -> pd.DataFrame:
        """Fetch a FRED series. Returns DataFrame with columns: date, value, source, series_id.

        Args:
            series_id: FRED series ID (e.g., "CPIAUCSL").
            start: Observation start date "YYYY-MM-DD".
            end: Observation end date "YYYY-MM-DD".
            units: FRED unit transformation. Options:
                "lin" (default, no transform), "chg" (change),
                "ch1" (change from year ago), "pch" (% change),
                "pc1" (% change from year ago), "pca" (compounded annual rate of change),
                "cch" (continuously compounded rate of change),
                "cca" (continuously compounded annual rate of change),
                "log" (natural log).
        """
        kwargs = {}
        if start:
            kwargs["observation_start"] = start
        if end:
            kwargs["observation_end"] = end
        if units:
            kwargs["units"] = units

        raw = self.fred.get_series(series_id, **kwargs)

        if raw is None or raw.empty:
            return pd.DataFrame(columns=["date", "value", "source", "series_id"])

        df = pd.DataFrame({
            "date": raw.index,
            "value": raw.values,
            "source": "FRED",
            "series_id": series_id,
        })
        df["date"] = pd.to_datetime(df["date"])
        return df

    def fetch_all_releases(self, series_id: str) -> pd.DataFrame:
        """Fetch all ALFRED vintages for a series.

        Returns DataFrame with columns: series_id, date, realtime_start, value.
        """
        raw = self.fred.get_series_all_releases(series_id)

        if raw is None or raw.empty:
            return pd.DataFrame(columns=["series_id", "date", "realtime_start", "value"])

        df = raw.reset_index()
        # fredapi returns columns: date, realtime_start, value (with date as index)
        # After reset_index, columns depend on version but typically: date, realtime_start, value
        df = df.rename(columns={c: c.strip() for c in df.columns})

        # Ensure expected columns exist
        if "date" not in df.columns and df.index.name == "date":
            df = df.reset_index()

        df["series_id"] = series_id
        df["date"] = pd.to_datetime(df["date"])
        df["realtime_start"] = pd.to_datetime(df["realtime_start"])

        return df[["series_id", "date", "realtime_start", "value"]]

    def fetch_series_info(self, series_id: str) -> dict:
        """Fetch metadata for a FRED series."""
        info = self.fred.get_series_info(series_id)
        return info.to_dict() if hasattr(info, "to_dict") else dict(info)

    def supports(self, indicator: str, country: str) -> bool:
        """FRED only supports US data."""
        return country == "US"
