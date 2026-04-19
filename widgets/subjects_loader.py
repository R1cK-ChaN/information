"""Load the subject vocabulary from YAML and sync it into the catalog."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config" / "subjects.yaml"


def load_subjects_yaml(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Read ``config/subjects.yaml`` and return the ``subjects`` list."""
    src = Path(path) if path else _DEFAULT_PATH
    with src.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    subjects = data.get("subjects") or []
    if not isinstance(subjects, list):
        raise ValueError(f"{src}: top-level 'subjects' must be a list")
    return subjects


def sync_from_yaml(catalog, path: str | Path | None = None) -> int:
    """Load the YAML and push it through ``catalog.sync_subjects``.

    Returns the number of subjects synced.
    """
    subjects = load_subjects_yaml(path)
    catalog.sync_subjects(subjects)
    return len(subjects)
