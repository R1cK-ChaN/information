#!/usr/bin/env python3
"""One-shot backfill: tag existing catalog rows with subject_ids.

Run this once after introducing the subject-tagging schema (issue #2) to
populate ``item_subjects`` for rows that were inserted before the tagger
was wired into the ingest path.

Usage:
    python scripts/backfill_subjects.py
    python scripts/backfill_subjects.py --catalog /path/to/catalog.db
    python scripts/backfill_subjects.py --dry-run
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from widgets.catalog import Catalog
from widgets.subjects_loader import sync_from_yaml
from widgets.tagger import SubjectTagger


def _build_tagger(subjects_path: Path) -> SubjectTagger:
    """Build the tagger in an in-memory catalog so dry-run never writes to
    the target DB.
    """
    vocab = Catalog(":memory:")
    sync_from_yaml(vocab, subjects_path)
    return SubjectTagger(vocab)


def _iter_items(conn: sqlite3.Connection):
    yield from conn.execute("SELECT sha256, title, subject_id FROM items")


def backfill(catalog: Catalog, tagger: SubjectTagger, *, dry_run: bool) -> dict:
    """Run the backfill against an opened *catalog* (read-write).

    Callers who need dry-run guarantees should not call this path — use
    :func:`run_dry` instead, which opens the target DB read-only.
    """
    conn = catalog._conn
    total = 0
    tagged = 0
    skipped_already = 0

    for sha, title, raw_subject_id in _iter_items(conn):
        total += 1
        existing = conn.execute(
            "SELECT COUNT(*) FROM item_subjects WHERE item_sha = ?",
            (sha,),
        ).fetchone()[0]
        if existing:
            skipped_already += 1
            continue

        merged = _tag_one(tagger, title, raw_subject_id)
        if not merged:
            continue

        if not dry_run:
            conn.executemany(
                "INSERT INTO item_subjects (item_sha, subject_id, confidence) VALUES (?,?,?)",
                [(sha, sid, conf) for sid, conf in merged.items()],
            )
        tagged += 1

    if not dry_run:
        conn.commit()

    return {"total": total, "tagged": tagged, "skipped_already": skipped_already}


def run_dry(target_db: Path, subjects_path: Path) -> dict:
    """Dry-run path: open *target_db* read-only so nothing is mutated (no
    new tables, no vocab sync, no item_subjects writes).
    """
    tagger = _build_tagger(subjects_path)
    uri = f"file:{target_db}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        # item_subjects may not exist on a pre-tagging DB — treat as zero.
        try:
            existing_ids = {
                r[0] for r in conn.execute("SELECT item_sha FROM item_subjects")
            }
        except sqlite3.OperationalError:
            existing_ids = set()

        total = 0
        tagged = 0
        skipped_already = 0
        for sha, title, raw_subject_id in _iter_items(conn):
            total += 1
            if sha in existing_ids:
                skipped_already += 1
                continue
            merged = _tag_one(tagger, title, raw_subject_id)
            if merged:
                tagged += 1
        return {"total": total, "tagged": tagged, "skipped_already": skipped_already}
    finally:
        conn.close()


def _tag_one(tagger: SubjectTagger, title, raw_subject_id) -> dict[str, float]:
    merged: dict[str, float] = {}
    for sid, conf in tagger.tag_text(title):
        merged[sid] = conf
    for sid, conf in tagger.tag_fred_series(raw_subject_id):
        if conf > merged.get(sid, 0.0):
            merged[sid] = conf
    return merged


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--catalog",
        default=str(_REPO_ROOT / "output" / "catalog.db"),
        help="Path to catalog.db (default: output/catalog.db)",
    )
    ap.add_argument(
        "--subjects",
        default=str(_REPO_ROOT / "config" / "subjects.yaml"),
        help="Path to subjects.yaml",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not write. Opens the target DB read-only so the vocabulary is "
             "not synced into it either.",
    )
    args = ap.parse_args()

    catalog_path = Path(args.catalog)
    subjects_path = Path(args.subjects)

    if args.dry_run:
        stats = run_dry(catalog_path, subjects_path)
    else:
        catalog = Catalog(catalog_path)
        sync_from_yaml(catalog, subjects_path)
        tagger = SubjectTagger(catalog)
        stats = backfill(catalog, tagger, dry_run=False)
        catalog.close()

    print(
        f"Backfill {'(dry-run) ' if args.dry_run else ''}complete: "
        f"scanned={stats['total']} tagged={stats['tagged']} "
        f"skipped_already_tagged={stats['skipped_already']}"
    )


if __name__ == "__main__":
    main()
