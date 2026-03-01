"""Dedup hashing for gov_report.

Uses sha256(url + "|" + publish_date) since the same report page may change
layout over time but the content identity is (url, publish_date).
"""

from __future__ import annotations

import hashlib


def content_sha(url: str, publish_date: str) -> str:
    """Return hex SHA-256 of url|publish_date."""
    payload = f"{url}|{publish_date}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
