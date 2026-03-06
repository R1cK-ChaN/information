"""Filter matching logic for SSE and REST endpoints."""

from __future__ import annotations

_FILTER_FIELDS = (
    "impact_level",
    "market",
    "asset_class",
    "sector",
    "institution",
    "event_type",
)


def matches_filter(item: dict, **kwargs) -> bool:
    """Return True if *item* matches all provided filter values.

    Comparison is case-insensitive substring match.  Filter keys that are
    ``None`` (not supplied) are skipped.
    """
    for field in _FILTER_FIELDS:
        value = kwargs.get(field)
        if value is None:
            continue
        item_val = item.get(field)
        if item_val is None:
            return False
        if value.lower() not in str(item_val).lower():
            return False
    return True
