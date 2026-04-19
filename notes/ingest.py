"""Ingest research notes from a markdown input folder into the shared catalog.

Each input file must start with a YAML frontmatter block containing at minimum:

    ---
    title: "My take on Q3 CPI"
    date: "2026-04-19"
    subject_id: econ.cpi
    ---

The body below the second ``---`` delimiter is the note content. Ingesting a
note:

  * writes ``output/notes/<sha12>.json`` with the metadata + markdown body,
  * writes ``6_information_layer/notes/<sha12>.md`` as the canonical export
    (same file layout the news / gov_report pipelines use),
  * inserts a row into ``catalog.db`` with ``source='notes'`` tagged with the
    frontmatter ``subject_id`` at confidence 1.0.

Running again re-ingests any file whose content has changed. Files whose sha
is already in the catalog are skipped.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from widgets.catalog import Catalog  # noqa: E402

logger = logging.getLogger(__name__)

_FRONTMATTER_RE_FENCE = "---"


def parse_note(path: Path) -> tuple[dict[str, Any], str]:
    """Split a note into ``(frontmatter_dict, body_markdown)``.

    Raises ``ValueError`` if frontmatter is missing or the required fields
    (``title``, ``date``, ``subject_id``) aren't present.
    """
    text = path.read_text(encoding="utf-8")
    if not text.startswith(_FRONTMATTER_RE_FENCE):
        raise ValueError(f"{path}: missing YAML frontmatter fence")
    rest = text[len(_FRONTMATTER_RE_FENCE):].lstrip("\n")
    try:
        end = rest.index(f"\n{_FRONTMATTER_RE_FENCE}")
    except ValueError as exc:
        raise ValueError(f"{path}: unterminated frontmatter") from exc
    fm_text = rest[:end]
    body = rest[end + len(_FRONTMATTER_RE_FENCE) + 1:].lstrip("\n")

    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"{path}: malformed YAML frontmatter: {exc}") from exc
    if not isinstance(fm, dict):
        raise ValueError(f"{path}: frontmatter must be a mapping")

    for required in ("title", "date", "subject_id"):
        if not fm.get(required):
            raise ValueError(f"{path}: frontmatter is missing '{required}'")
    return fm, body


def ingest_notes(
    input_dir: Path,
    *,
    catalog: Catalog,
    output_root: Path,
    export_root: Path,
) -> dict[str, int]:
    """Ingest every ``*.md`` file under *input_dir*.

    Returns ``{"ingested": N, "skipped": M, "failed": K}``.
    """
    output_root.mkdir(parents=True, exist_ok=True)
    export_root.mkdir(parents=True, exist_ok=True)

    stats = {"ingested": 0, "skipped": 0, "failed": 0}
    for md in sorted(input_dir.glob("*.md")):
        try:
            fm, body = parse_note(md)
        except ValueError as exc:
            logger.error("skip %s: %s", md, exc)
            stats["failed"] += 1
            continue

        # Hash the full file (frontmatter + body) so editing only the
        # subject_id / title / date forces a fresh catalog row instead of
        # silently skipping the note.
        sha = hashlib.sha256(md.read_bytes()).hexdigest()
        if catalog.has(sha):
            stats["skipped"] += 1
            continue

        sha12 = sha[:12]
        json_path = output_root / f"{sha12}.json"
        export_path = export_root / f"{sha12}.md"

        json_path.write_text(
            json.dumps(
                {
                    "sha256": sha,
                    "title": fm["title"],
                    "publish_date": str(fm["date"]),
                    "subject_id": fm["subject_id"],
                    "author": fm.get("author"),
                    "markdown": body,
                },
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )
        export_path.write_text(md.read_text(encoding="utf-8"), encoding="utf-8")

        catalog.insert(
            {
                "sha256": sha,
                "source": "notes",
                "title": fm["title"],
                "publish_date": str(fm["date"]),
                "subject_id": fm["subject_id"],
                "institution": fm.get("author"),
                "processed_at": int(time.time()),
            },
            json_path,
            subjects=[(fm["subject_id"], 1.0)],
            body_text=body,
        )
        stats["ingested"] += 1

    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest research notes into the catalog")
    parser.add_argument(
        "--input",
        type=Path,
        default=_REPO_ROOT / "6_information_layer" / "notes_input",
        help="Folder containing *.md notes with YAML frontmatter",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=_REPO_ROOT / "output" / "catalog.db",
        help="Path to the shared catalog.db",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=_REPO_ROOT / "output" / "notes",
    )
    parser.add_argument(
        "--export-root",
        type=Path,
        default=_REPO_ROOT / "6_information_layer" / "notes",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if not args.input.exists():
        print(f"input dir does not exist: {args.input}", file=sys.stderr)
        return 2

    catalog = Catalog(args.catalog)
    try:
        stats = ingest_notes(
            args.input,
            catalog=catalog,
            output_root=args.output_root,
            export_root=args.export_root,
        )
    finally:
        catalog.close()

    print(
        f"ingested={stats['ingested']} skipped={stats['skipped']} failed={stats['failed']}"
    )
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
