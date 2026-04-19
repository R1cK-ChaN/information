"""Subject tagger: maps source-native identifiers and free-text titles to
canonical subject IDs using the alias vocabulary stored in the catalog.

v1 strategy (lean — see issue #2):
  * Structured sources (FRED series_id, calendar indicator) resolve via
    exact alias lookup at confidence 1.0.
  * News / newsletter titles resolve via word-boundary regex at 0.8.
  * No body scoring, no disambiguation rules, no LLM fallback. Add those
    when observed precision/recall justifies the complexity.
"""

from __future__ import annotations

import re
from typing import Iterable


STRUCTURED_CONFIDENCE = 1.0
TITLE_CONFIDENCE = 0.8


class SubjectTagger:
    """Compiled view over the ``subjects`` + ``subject_aliases`` tables.

    Build once per process (the regex list is small but compiling per call
    wastes work). Callers rebuild by constructing a new instance.
    """

    def __init__(self, catalog) -> None:
        self._catalog = catalog
        self._title_patterns: list[tuple[str, re.Pattern[str]]] = []
        self._fred_index: dict[str, str] = {}
        self._calendar_index: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        conn = self._catalog._conn
        rows = conn.execute(
            "SELECT subject_id, alias_type, alias_value FROM subject_aliases"
        ).fetchall()
        for sid, atype, aval in rows:
            if atype == "title_regex":
                self._title_patterns.append(
                    (sid, re.compile(aval, re.IGNORECASE))
                )
            elif atype == "fred_series":
                self._fred_index[aval.upper()] = sid
            elif atype == "calendar_indicator":
                self._calendar_index[aval.lower()] = sid

    # ---- public API -------------------------------------------------------

    def tag_text(self, title: str | None) -> list[tuple[str, float]]:
        """Match title against all ``title_regex`` aliases.

        Returns one tuple per matched subject (deduped). Confidence is a
        flat 0.8 in v1 — no scoring.
        """
        if not title:
            return []
        hits: set[str] = set()
        for sid, pat in self._title_patterns:
            if pat.search(title):
                hits.add(sid)
        return [(sid, TITLE_CONFIDENCE) for sid in sorted(hits)]

    def tag_fred_series(
        self, series_ids: str | Iterable[str] | None
    ) -> list[tuple[str, float]]:
        """Resolve one or more FRED series IDs to subject tags."""
        if not series_ids:
            return []
        if isinstance(series_ids, str):
            series_ids = [series_ids]
        hits: set[str] = set()
        for sid in series_ids:
            if not sid:
                continue
            mapped = self._fred_index.get(sid.upper())
            if mapped:
                hits.add(mapped)
        return [(sid, STRUCTURED_CONFIDENCE) for sid in sorted(hits)]

    def tag_calendar_indicator(
        self, indicator: str | None
    ) -> list[tuple[str, float]]:
        """Resolve a calendar indicator string to subject tags."""
        if not indicator:
            return []
        mapped = self._calendar_index.get(indicator.lower())
        if not mapped:
            return []
        return [(mapped, STRUCTURED_CONFIDENCE)]

    def tag_structured(
        self,
        *,
        fred_series: str | Iterable[str] | None = None,
        calendar_indicator: str | None = None,
    ) -> list[tuple[str, float]]:
        """Resolve structured-source identifiers to subject tags (confidence 1.0)."""
        hits: dict[str, float] = {}
        for sid, conf in self.tag_fred_series(fred_series):
            hits[sid] = conf
        for sid, conf in self.tag_calendar_indicator(calendar_indicator):
            hits[sid] = conf
        return sorted(hits.items())
