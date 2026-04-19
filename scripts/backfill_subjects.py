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
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from widgets.catalog import Catalog
from widgets.subjects_loader import sync_from_yaml
from widgets.tagger import SubjectTagger


def backfill(catalog: Catalog, tagger: SubjectTagger, *, dry_run: bool) -> dict:
    conn = catalog._conn
    rows = conn.execute(
        "SELECT sha256, title, subject_id FROM items"
    ).fetchall()

    total = 0
    tagged = 0
    skipped_already = 0

    for sha, title, raw_subject_id in rows:
        total += 1
        existing = conn.execute(
            "SELECT COUNT(*) FROM item_subjects WHERE item_sha = ?",
            (sha,),
        ).fetchone()[0]
        if existing:
            skipped_already += 1
            continue

        merged: dict[str, float] = {}
        for sid, conf in tagger.tag_text(title):
            merged[sid] = conf
        for sid, conf in tagger.tag_fred_series(raw_subject_id):
            if conf > merged.get(sid, 0.0):
                merged[sid] = conf

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
    ap.add_argument("--dry-run", action="store_true", help="Do not write")
    args = ap.parse_args()

    catalog = Catalog(args.catalog)
    sync_from_yaml(catalog, args.subjects)
    tagger = SubjectTagger(catalog)

    stats = backfill(catalog, tagger, dry_run=args.dry_run)
    catalog.close()

    print(
        f"Backfill {'(dry-run) ' if args.dry_run else ''}complete: "
        f"scanned={stats['total']} tagged={stats['tagged']} "
        f"skipped_already_tagged={stats['skipped_already']}"
    )


if __name__ == "__main__":
    main()
