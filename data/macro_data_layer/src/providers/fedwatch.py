"""FedWatch rate-expectations provider.

Uses rateprobability.com's public ``/api/latest`` endpoint as a free
CME-FedWatch equivalent. One call returns the current snapshot: the
spot Fed funds band plus one implied-rate row per upcoming FOMC meeting.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_ENDPOINT = "https://rateprobability.com/api/latest"


@dataclass
class FedWatchMeetingRow:
    meeting_date: str        # ISO "YYYY-MM-DD"
    implied_rate: float | None
    prob_move_pct: float | None
    prob_is_cut: bool
    change_bps: float | None


@dataclass
class FedWatchSnapshot:
    snapshot_date: str       # ISO "YYYY-MM-DD" (the ``as_of`` field)
    midpoint: float | None
    most_recent_effr: float | None
    current_band: str | None
    rows: list[FedWatchMeetingRow]


class FedWatchProvider:
    """Provider for forward FOMC rate expectations."""

    provider_name = "RATEPROBABILITY"

    def __init__(self, endpoint: str = _DEFAULT_ENDPOINT, timeout: float = 20.0) -> None:
        self.endpoint = endpoint
        self.timeout = timeout

    def _fetch_json(self) -> dict[str, Any]:
        req = urllib.request.Request(
            self.endpoint,
            headers={
                "Accept": "application/json",
                "User-Agent": "analyst-info-layer/0.1",
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def fetch_latest(self) -> FedWatchSnapshot:
        """Fetch the current FedWatch snapshot."""
        payload = self._fetch_json()
        today = payload.get("today") or {}
        rows_raw = today.get("rows") or []

        rows = [
            FedWatchMeetingRow(
                meeting_date=r["meeting_iso"],
                implied_rate=_as_float(r.get("implied_rate_post_meeting")),
                prob_move_pct=_as_float(r.get("prob_move_pct")),
                prob_is_cut=bool(r.get("prob_is_cut")),
                change_bps=_as_float(r.get("change_bps")),
            )
            for r in rows_raw
            if r.get("meeting_iso")
        ]
        return FedWatchSnapshot(
            snapshot_date=today.get("as_of"),
            midpoint=_as_float(today.get("midpoint")),
            most_recent_effr=_as_float(today.get("most_recent_effr")),
            current_band=today.get("current band"),
            rows=rows,
        )


def _as_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
