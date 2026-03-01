"""Base provider ABC with retry logic."""

import logging
import time
from abc import ABC, abstractmethod

import pandas as pd

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_DELAY = 2  # seconds


class BaseProvider(ABC):
    """Abstract base class for data providers."""

    provider_name: str = "base"

    @abstractmethod
    def fetch_series(self, series_id: str, start: str | None = None, end: str | None = None) -> pd.DataFrame:
        """Fetch time-series data. Returns DataFrame with columns: date, value, source, series_id."""
        ...

    @abstractmethod
    def supports(self, indicator: str, country: str) -> bool:
        """Check if this provider can serve the given indicator+country."""
        ...

    def fetch_with_retry(self, method, *args, **kwargs) -> pd.DataFrame:
        """Call a fetch method with exponential backoff retry.

        Args:
            method: The fetch method to call (e.g., self.fetch_series).
            *args, **kwargs: Passed through to the method.
        """
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return method(*args, **kwargs)
            except Exception as e:
                if attempt == MAX_RETRIES:
                    raise
                delay = BASE_DELAY * attempt
                logger.warning(
                    "[%s] Attempt %d/%d failed: %s. Retry in %ds",
                    self.provider_name, attempt, MAX_RETRIES, e, delay,
                )
                time.sleep(delay)
