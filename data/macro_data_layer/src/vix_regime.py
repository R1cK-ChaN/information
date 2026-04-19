"""VIX regime classifier.

One series, two thresholds, three labels. Not a generic operator framework —
this is the single regime the information layer cares about for classification
(issue #3, scope item 5).
"""

from __future__ import annotations

import math

LOW_THRESHOLD = 15.0
STRESSED_THRESHOLD = 25.0


def classify_vix_regime(value: float | None) -> str | None:
    """Classify a VIX close into a regime label.

    Returns ``"low"`` (<15), ``"elevated"`` (15-25), or ``"stressed"`` (>=25).
    ``None``/``NaN``/``inf`` → ``None`` so missing or malformed prints don't
    get a synthetic label — FRED and pandas both return ``NaN`` for
    closed-market or blank observations.
    """
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    if v < LOW_THRESHOLD:
        return "low"
    if v < STRESSED_THRESHOLD:
        return "elevated"
    return "stressed"
