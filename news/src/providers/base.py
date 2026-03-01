"""Base provider ABC with retry logic."""

import logging
import time
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_DELAY = 2  # seconds


class BaseProvider(ABC):
    """Abstract base class for news providers."""

    provider_name: str = "base"

    @abstractmethod
    def fetch(self, url: str, **kwargs) -> list[dict]:
        """Fetch news items from a source. Returns list of raw item dicts."""
        ...

    def fetch_with_retry(self, url: str, **kwargs) -> list[dict]:
        """Call fetch with exponential backoff retry."""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return self.fetch(url, **kwargs)
            except Exception as e:
                if attempt == MAX_RETRIES:
                    raise
                delay = BASE_DELAY * attempt
                logger.warning(
                    "[%s] Attempt %d/%d failed for %s: %s. Retry in %ds",
                    self.provider_name, attempt, MAX_RETRIES, url, e, delay,
                )
                time.sleep(delay)
        return []  # unreachable, but satisfies type checker
