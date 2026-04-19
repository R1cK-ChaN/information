"""Round-trip test for the notes ingestion path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from notes.ingest import ingest_notes, parse_note
from widgets.catalog import Catalog


_SAMPLE = """---
title: "Thoughts on Q3 CPI"
date: "2026-04-19"
subject_id: econ.cpi
author: ewan
---

# Body

Inflation looks sticky in services.
"""


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


class TestParseNote:
    def test_happy_path(self, tmp_path):
        p = _write(tmp_path / "n.md", _SAMPLE)
        fm, body = parse_note(p)
        assert fm["title"] == "Thoughts on Q3 CPI"
        assert fm["subject_id"] == "econ.cpi"
        assert "Inflation looks sticky" in body

    def test_missing_frontmatter(self, tmp_path):
        p = _write(tmp_path / "n.md", "no frontmatter here")
        with pytest.raises(ValueError, match="missing YAML frontmatter"):
            parse_note(p)

    def test_missing_required_field(self, tmp_path):
        text = "---\ntitle: foo\ndate: 2026-01-01\n---\nbody"
        p = _write(tmp_path / "n.md", text)
        with pytest.raises(ValueError, match="subject_id"):
            parse_note(p)

    def test_malformed_yaml_becomes_value_error(self, tmp_path):
        # Unterminated flow sequence triggers a yaml.YAMLError — must surface
        # as ValueError so the ingest loop's except clause can catch it.
        text = "---\ntitle: [oops\n---\nbody"
        p = _write(tmp_path / "n.md", text)
        with pytest.raises(ValueError, match="malformed YAML"):
            parse_note(p)


class TestIngestNotes:
    def test_end_to_end_round_trip(self, tmp_path):
        input_dir = tmp_path / "in"
        input_dir.mkdir()
        _write(input_dir / "q3_cpi.md", _SAMPLE)

        catalog = Catalog(tmp_path / "cat.db")
        output_root = tmp_path / "out"
        export_root = tmp_path / "export"

        stats = ingest_notes(
            input_dir,
            catalog=catalog,
            output_root=output_root,
            export_root=export_root,
        )
        assert stats == {"ingested": 1, "skipped": 0, "failed": 0}

        # Catalog row
        rows = catalog.get_latest(10, source="notes")
        assert len(rows) == 1
        row = rows[0]
        assert row["source"] == "notes"
        assert row["title"] == "Thoughts on Q3 CPI"
        assert row["institution"] == "ewan"

        # FTS over the body picks it up
        fts = catalog.search_fts("inflation")
        assert len(fts) == 1 and fts[0]["sha256"] == row["sha256"]

        # Subject tag
        tagged = catalog.get_items_by_subject("econ.cpi")
        assert any(r["sha256"] == row["sha256"] for r in tagged)

        # Canonical export + json files exist, hash-named
        sha12 = row["sha256"][:12]
        assert (export_root / f"{sha12}.md").exists()
        payload = json.loads((output_root / f"{sha12}.json").read_text(encoding="utf-8"))
        assert payload["subject_id"] == "econ.cpi"
        assert "Inflation looks sticky" in payload["markdown"]

        catalog.close()

    def test_rerun_skips_unchanged(self, tmp_path):
        input_dir = tmp_path / "in"
        input_dir.mkdir()
        _write(input_dir / "n.md", _SAMPLE)
        catalog = Catalog(tmp_path / "cat.db")
        opts = dict(
            catalog=catalog,
            output_root=tmp_path / "out",
            export_root=tmp_path / "export",
        )

        ingest_notes(input_dir, **opts)
        stats = ingest_notes(input_dir, **opts)
        assert stats == {"ingested": 0, "skipped": 1, "failed": 0}
        catalog.close()

    def test_malformed_note_counted_as_failed(self, tmp_path):
        input_dir = tmp_path / "in"
        input_dir.mkdir()
        _write(input_dir / "good.md", _SAMPLE)
        _write(input_dir / "bad.md", "no frontmatter")

        catalog = Catalog(tmp_path / "cat.db")
        stats = ingest_notes(
            input_dir,
            catalog=catalog,
            output_root=tmp_path / "out",
            export_root=tmp_path / "export",
        )
        assert stats["ingested"] == 1
        assert stats["failed"] == 1
        catalog.close()

    def test_malformed_yaml_does_not_abort_run(self, tmp_path):
        """A yaml.YAMLError in one file used to propagate out of ingest_notes;
        it must be caught and counted as failed alongside the surviving notes."""
        input_dir = tmp_path / "in"
        input_dir.mkdir()
        _write(input_dir / "good.md", _SAMPLE)
        _write(input_dir / "broken.md", "---\ntitle: [oops\n---\nbody")

        catalog = Catalog(tmp_path / "cat.db")
        stats = ingest_notes(
            input_dir,
            catalog=catalog,
            output_root=tmp_path / "out",
            export_root=tmp_path / "export",
        )
        assert stats["ingested"] == 1
        assert stats["failed"] == 1
        catalog.close()

    def test_frontmatter_edit_triggers_reingest(self, tmp_path):
        """Changing subject_id or title without touching the body must force a
        new catalog row — the dedup key hashes the full file, not just the body."""
        input_dir = tmp_path / "in"
        input_dir.mkdir()
        note = input_dir / "n.md"
        _write(note, _SAMPLE)

        catalog = Catalog(tmp_path / "cat.db")
        opts = dict(
            catalog=catalog,
            output_root=tmp_path / "out",
            export_root=tmp_path / "export",
        )

        ingest_notes(input_dir, **opts)
        before = catalog.get_latest(10, source="notes")
        assert len(before) == 1
        assert before[0]["subject_id"] == "econ.cpi"

        # Rewrite only the frontmatter; body is byte-identical.
        _write(
            note,
            _SAMPLE.replace("subject_id: econ.cpi", "subject_id: econ.ppi"),
        )
        stats = ingest_notes(input_dir, **opts)
        assert stats["ingested"] == 1  # a genuinely new row, not a skip

        after = catalog.get_latest(10, source="notes")
        assert {r["subject_id"] for r in after} >= {"econ.ppi"}
        catalog.close()
