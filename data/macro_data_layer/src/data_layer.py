"""MacroDataLayer — agent entry point for macro economic data."""

import logging
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import yaml
from dotenv import load_dotenv

from .storage import Storage
from .registry import Registry
from .providers.fred import FREDProvider

logger = logging.getLogger(__name__)

# Find project root (where config/ lives)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT = _PROJECT_ROOT.parent.parent


class MacroDataLayer:
    """Centralized data layer for macro economic research.

    Usage:
        dl = MacroDataLayer()
        cpi = dl.get("CPI", "US")
        gdp_vintage = dl.get_vintage("GDP", "US", as_of="2024-01-31")
    """

    def __init__(self, config_path: str | Path | None = None):
        load_dotenv(_REPO_ROOT / ".env")
        load_dotenv(_PROJECT_ROOT / ".env", override=True)

        if config_path is None:
            config_path = _PROJECT_ROOT / "config" / "data_layer.yaml"
        with open(config_path) as f:
            self.config = yaml.safe_load(f)

        # Resolve sqlite path relative to project root
        db_path = _PROJECT_ROOT / self.config["storage"]["sqlite_path"]
        self.storage = Storage(db_path)
        self.registry = Registry()

        # Init FRED provider
        fred_cfg = self.config["providers"]["fred"]
        api_key = os.getenv(fred_cfg["api_key_env"])
        if not api_key:
            raise ValueError(
                f"FRED API key not found. Set {fred_cfg['api_key_env']} in environment or .env"
            )
        self.fred = FREDProvider(api_key)

        # TTL config
        self.ttl_config = self.config.get("ttl", {})

    def _get_ttl_hours(self, frequency: str) -> int:
        """Get TTL in hours for a given frequency."""
        return self.ttl_config.get(frequency, 24)

    def _is_stale(self, series_key: str, ttl_hours: int) -> bool:
        """Check if a series needs refreshing based on its sync_log."""
        info = self.storage.get_sync_info(series_key)
        if info is None or info["last_refresh"] is None:
            return True
        last_refresh = datetime.fromisoformat(info["last_refresh"])
        if last_refresh.tzinfo is None:
            last_refresh = last_refresh.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - last_refresh > timedelta(hours=ttl_hours)

    # Lookback days per frequency for catching revisions during refresh.
    # Monthly series (CPI, NFP) are typically revised within 2 months.
    # Quarterly series (GDP) get 3 revisions over ~3 months.
    _REVISION_LOOKBACK = {
        "daily": 0,       # daily series are not revised
        "weekly": 0,      # weekly series are not revised
        "monthly": 90,    # ~3 months catches most monthly revisions
        "quarterly": 180, # ~6 months catches advance → second → third GDP estimates
    }

    def get(
        self,
        indicator: str,
        country: str = "US",
        start: str | None = None,
        end: str | None = None,
        units: str | None = None,
    ) -> pd.DataFrame:
        """Get time-series data for an indicator. Local-first with lazy refresh.

        Args:
            indicator: Canonical indicator name (e.g., "CPI", "GDP_REAL").
            country: ISO2 country code. Default "US".
            start: Optional start date "YYYY-MM-DD".
            end: Optional end date "YYYY-MM-DD".
            units: FRED unit transformation applied server-side. Options:
                None (raw levels), "chg" (change), "ch1" (change from year ago),
                "pch" (% change), "pc1" (% change from year ago),
                "pca" (compounded annual rate of change), "log" (natural log).
                When set, data is fetched live from FRED (not cached), since
                transformed values are not stored locally.

        Returns:
            DataFrame with columns: date, value, source, series_id.
        """
        info = self.registry.get_indicator(indicator)
        series_key = f"{indicator}:{country}"

        if units:
            # Transformed data is fetched directly — don't cache transformed values
            return self._fetch_transformed(info, start, end, units)

        ttl = self._get_ttl_hours(info.frequency)
        if self._is_stale(series_key, ttl):
            self._refresh_series(indicator, country, info)

        return self.storage.read_series(series_key, start, end)

    def _fetch_transformed(self, info, start, end, units) -> pd.DataFrame:
        """Fetch series with a FRED units transformation (not cached)."""
        return self.fred.fetch_with_retry(
            self.fred.fetch_series, info.fred_series_id,
            start=start, end=end, units=units,
        )

    def _refresh_series(self, indicator: str, country: str, info=None):
        """Refresh a single series from its provider.

        Uses a revision-aware lookback window so that revised observations
        (e.g., GDP advance → second estimate, CPI preliminary → final)
        are picked up via INSERT OR REPLACE in storage.
        """
        if info is None:
            info = self.registry.get_indicator(indicator)
        series_key = f"{indicator}:{country}"

        if not self.fred.supports(indicator, country):
            logger.warning("No provider supports %s for country %s", indicator, country)
            return

        try:
            last_date = self.storage.get_last_date(series_key)
            if last_date:
                lookback_days = self._REVISION_LOOKBACK.get(info.frequency, 0)
                start = (
                    pd.Timestamp(last_date) - pd.Timedelta(days=lookback_days)
                ).strftime("%Y-%m-%d")
                df = self.fred.fetch_with_retry(
                    self.fred.fetch_series, info.fred_series_id, start=start
                )
            else:
                # Full history
                df = self.fred.fetch_with_retry(self.fred.fetch_series, info.fred_series_id)

            if not df.empty:
                self.storage.upsert_series(series_key, df)

            new_last = self.storage.get_last_date(series_key)
            self.storage.update_sync(series_key, new_last)
            logger.info("Refreshed %s: %d rows (lookback=%s)", series_key, len(df), info.frequency)
        except Exception as e:
            logger.error("Failed to refresh %s: %s", series_key, e)
            self.storage.update_sync(series_key, error=True)
            raise

    def get_vintage(
        self, indicator: str, country: str = "US", as_of: str | None = None
    ) -> pd.DataFrame:
        """Point-in-time query: what was known as of a given date.

        Args:
            indicator: Canonical indicator name (must be ALFRED-tracked).
            country: ISO2 country code. Default "US".
            as_of: Date string "YYYY-MM-DD". If None, returns latest vintage.

        Returns:
            DataFrame with columns: date, value, realtime_start.
        """
        info = self.registry.get_indicator(indicator)
        if not info.alfred_tracked:
            raise ValueError(
                f"Indicator '{indicator}' is not tracked for revisions. "
                f"ALFRED-tracked indicators: use get_revisions() to check availability."
            )

        series_id = info.fred_series_id
        if as_of is None:
            as_of = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        return self.storage.read_vintage(series_id, as_of)

    def get_revisions(self, indicator: str, country: str = "US") -> pd.DataFrame:
        """Full revision history for an ALFRED-tracked indicator.

        Args:
            indicator: Canonical indicator name.
            country: ISO2 country code. Default "US".

        Returns:
            DataFrame with columns: date, realtime_start, value.
        """
        info = self.registry.get_indicator(indicator)
        if not info.alfred_tracked:
            raise ValueError(f"Indicator '{indicator}' is not tracked for revisions.")
        return self.storage.read_all_vintages(info.fred_series_id)

    def list_indicators(self, category: str | None = None) -> pd.DataFrame:
        """List available indicators as a DataFrame."""
        indicators = self.registry.list_indicators(category)
        return pd.DataFrame([
            {
                "name": i.canonical_name,
                "description": i.description,
                "category": i.category,
                "frequency": i.frequency,
                "fred_id": i.fred_series_id,
                "alfred_tracked": i.alfred_tracked,
            }
            for i in indicators
        ])

    def describe(self, indicator: str, country: str = "US") -> dict:
        """Return metadata for an indicator including sync status."""
        info = self.registry.get_indicator(indicator)
        series_key = f"{indicator}:{country}"
        sync = self.storage.get_sync_info(series_key)
        return {
            "canonical_name": info.canonical_name,
            "description": info.description,
            "category": info.category,
            "frequency": info.frequency,
            "fred_series_id": info.fred_series_id,
            "alfred_tracked": info.alfred_tracked,
            "ttl_hours": info.ttl_hours,
            "last_local_date": sync["last_local_date"] if sync else None,
            "last_refresh": sync["last_refresh"] if sync else None,
            "refresh_count": sync["refresh_count"] if sync else 0,
        }

    def refresh(self, indicator: str | None = None, country: str | None = None) -> dict:
        """Explicit refresh. If no args, refreshes all stale series.

        Returns:
            Summary dict: {"refreshed": N, "skipped": M, "failed": K, "errors": [...]}.
        """
        results = {"refreshed": 0, "skipped": 0, "failed": 0, "errors": []}

        if indicator:
            country = country or "US"
            try:
                self._refresh_series(indicator, country)
                results["refreshed"] = 1
            except Exception as e:
                results["failed"] = 1
                results["errors"].append(f"{indicator}:{country} — {e}")
            return results

        # Refresh all registered series
        for info in self.registry.list_indicators():
            c = country or "US"
            series_key = f"{info.canonical_name}:{c}"
            ttl = self._get_ttl_hours(info.frequency)
            if not self._is_stale(series_key, ttl):
                results["skipped"] += 1
                continue
            try:
                self._refresh_series(info.canonical_name, c, info)
                results["refreshed"] += 1
                time.sleep(0.5)  # rate limit courtesy
            except Exception as e:
                results["failed"] += 1
                results["errors"].append(f"{info.canonical_name}:{c} — {e}")

        return results

    def bootstrap(self) -> dict:
        """One-time initial data load: all 47 FRED series + 16 ALFRED revision histories.

        Returns:
            Summary: {"series_loaded": N, "vintages_loaded": M, "errors": [...]}.
        """
        results = {"series_loaded": 0, "vintages_loaded": 0, "errors": []}
        all_indicators = self.registry.list_indicators()

        # Phase 1: Fetch all series
        logger.info("Bootstrap: loading %d FRED series...", len(all_indicators))
        for info in all_indicators:
            series_key = f"{info.canonical_name}:US"
            try:
                df = self.fred.fetch_with_retry(self.fred.fetch_series, info.fred_series_id)
                if not df.empty:
                    self.storage.upsert_series(series_key, df)
                    last_date = self.storage.get_last_date(series_key)
                    self.storage.update_sync(series_key, last_date)
                    results["series_loaded"] += 1
                    logger.info("  [%d/%d] %s: %d rows",
                                results["series_loaded"], len(all_indicators),
                                info.canonical_name, len(df))
                time.sleep(0.5)
            except Exception as e:
                results["errors"].append(f"{info.canonical_name}: {e}")
                logger.error("  FAILED %s: %s", info.canonical_name, e)

        # Phase 2: Fetch ALFRED vintages
        alfred_ids = self.registry.get_alfred_series()
        logger.info("Bootstrap: loading %d ALFRED vintage histories...", len(alfred_ids))
        for series_id in alfred_ids:
            try:
                df = self.fred.fetch_with_retry(self.fred.fetch_all_releases, series_id)
                if not df.empty:
                    self.storage.upsert_vintages(series_id, df)
                    results["vintages_loaded"] += 1
                    logger.info("  [%d/%d] %s: %d vintage rows",
                                results["vintages_loaded"], len(alfred_ids),
                                series_id, len(df))
                time.sleep(1.0)
            except Exception as e:
                results["errors"].append(f"ALFRED {series_id}: {e}")
                logger.error("  FAILED ALFRED %s: %s", series_id, e)

        logger.info("Bootstrap complete: %d series, %d vintages, %d errors",
                     results["series_loaded"], results["vintages_loaded"], len(results["errors"]))
        return results

    def close(self):
        """Close the storage connection."""
        self.storage.close()
