"""Tests for the subject vocabulary loader + SubjectTagger."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from widgets.catalog import Catalog
from widgets.subjects_loader import load_subjects_yaml, sync_from_yaml
from widgets.tagger import SubjectTagger


REPO_ROOT = Path(__file__).resolve().parent.parent
SEED_YAML = REPO_ROOT / "config" / "subjects.yaml"
GOLDEN_PATH = REPO_ROOT / "tests" / "golden_tags.jsonl"


@pytest.fixture
def seeded_catalog():
    cat = Catalog(":memory:")
    sync_from_yaml(cat, SEED_YAML)
    yield cat
    cat.close()


@pytest.fixture
def tagger(seeded_catalog):
    return SubjectTagger(seeded_catalog)


# ----- Loader ---------------------------------------------------------------


class TestLoader:
    def test_seed_yaml_parses(self):
        subjects = load_subjects_yaml(SEED_YAML)
        assert len(subjects) == 20
        ids = {s["id"] for s in subjects}
        assert "econ.cpi" in ids
        assert "rate.us.fed_funds" in ids
        assert "commodity.wti" in ids

    def test_all_subjects_have_display_and_aliases(self):
        subjects = load_subjects_yaml(SEED_YAML)
        for sub in subjects:
            assert "id" in sub
            assert "display" in sub and sub["display"]
            assert "aliases" in sub

    def test_sync_populates_tables(self, seeded_catalog):
        rows = seeded_catalog.list_subjects()
        assert len(rows) == 20
        cpi_aliases = seeded_catalog.get_aliases("econ.cpi", "fred_series")
        assert "CPIAUCSL" in cpi_aliases

    def test_sync_is_idempotent(self, seeded_catalog):
        sync_from_yaml(seeded_catalog, SEED_YAML)
        sync_from_yaml(seeded_catalog, SEED_YAML)
        assert len(seeded_catalog.list_subjects()) == 20


# ----- Tagger: structured ---------------------------------------------------


class TestTagStructured:
    def test_fred_series_exact_match(self, tagger):
        tags = tagger.tag_fred_series("CPIAUCSL")
        assert tags == [("econ.cpi", 1.0)]

    def test_fred_series_case_insensitive(self, tagger):
        tags = tagger.tag_fred_series("cpiaucsl")
        assert tags == [("econ.cpi", 1.0)]

    def test_fred_series_unknown_returns_empty(self, tagger):
        assert tagger.tag_fred_series("UNKNOWN_SERIES_XYZ") == []

    def test_fred_series_multiple(self, tagger):
        tags = tagger.tag_fred_series(["CPIAUCSL", "FEDFUNDS"])
        sids = {t[0] for t in tags}
        assert sids == {"econ.cpi", "rate.us.fed_funds"}
        assert all(conf == 1.0 for _, conf in tags)

    def test_calendar_indicator_case_insensitive(self, tagger):
        assert tagger.tag_calendar_indicator("CPI") == [("econ.cpi", 1.0)]
        assert tagger.tag_calendar_indicator("cpi") == [("econ.cpi", 1.0)]

    def test_calendar_indicator_multi_word(self, tagger):
        tags = tagger.tag_calendar_indicator("Nonfarm Payrolls")
        assert tags == [("econ.us.nfp", 1.0)]

    def test_tag_structured_combines(self, tagger):
        tags = tagger.tag_structured(
            fred_series="PAYEMS", calendar_indicator="CPI"
        )
        sids = {t[0] for t in tags}
        assert sids == {"econ.us.nfp", "econ.cpi"}


# ----- Tagger: text ---------------------------------------------------------


class TestTagText:
    def test_exact_cpi_match(self, tagger):
        tags = tagger.tag_text("US CPI ticks higher in June")
        sids = {t[0] for t in tags}
        assert "econ.cpi" in sids

    def test_consumer_price_phrase(self, tagger):
        tags = tagger.tag_text("Consumer prices ease in Europe")
        sids = {t[0] for t in tags}
        assert "econ.cpi" in sids

    def test_multi_subject_title(self, tagger):
        tags = tagger.tag_text("FOMC hikes 25bp after hot CPI print")
        sids = {t[0] for t in tags}
        assert "econ.cpi" in sids
        assert "rate.us.fed_funds" in sids

    def test_word_boundary_prevents_substring_hit(self, tagger):
        # "scripting" must not match \bPPI\b
        tags = tagger.tag_text("Scripting a new era of data journalism")
        assert all(sid != "econ.us.ppi" for sid, _ in tags)

    def test_case_insensitive(self, tagger):
        lower = tagger.tag_text("cpi prints 3.2%")
        upper = tagger.tag_text("CPI PRINTS 3.2%")
        assert lower == upper

    def test_confidence_is_08(self, tagger):
        tags = tagger.tag_text("CPI higher")
        assert tags and all(conf == 0.8 for _, conf in tags)

    def test_empty_title_returns_empty(self, tagger):
        assert tagger.tag_text("") == []
        assert tagger.tag_text(None) == []

    def test_no_match_returns_empty(self, tagger):
        tags = tagger.tag_text("A quiet day in the markets")
        assert tags == []

    def test_ticker_match(self, tagger):
        tags = tagger.tag_text("AAPL hits record high")
        sids = {t[0] for t in tags}
        assert "equity.us.aapl" in sids

    def test_company_name_match(self, tagger):
        tags = tagger.tag_text("Nvidia ships new GPU")
        sids = {t[0] for t in tags}
        assert "equity.us.nvda" in sids


# ----- Catalog integration --------------------------------------------------


class TestCatalogSubjectsIntegration:
    def test_insert_with_subjects_populates_join_table(self, seeded_catalog):
        result = {
            "sha256": "a" * 64,
            "source": "news",
            "title": "CPI higher",
            "processed_at": int(time.time()),
        }
        seeded_catalog.insert(
            result, "/tmp/t.json", subjects=[("econ.cpi", 0.8)]
        )
        items = seeded_catalog.get_items_by_subject("econ.cpi")
        assert len(items) == 1
        assert items[0]["sha256"] == "a" * 64
        assert items[0]["subject_confidence"] == 0.8

    def test_insert_with_subjects_none_leaves_join_untouched(self, seeded_catalog):
        sha = "b" * 64
        seeded_catalog.insert(
            {"sha256": sha, "processed_at": 1}, "/tmp/b.json",
            subjects=[("econ.cpi", 0.8)],
        )
        # Second insert without subjects kwarg must NOT clear the tags.
        seeded_catalog.insert(
            {"sha256": sha, "processed_at": 2, "title": "updated"},
            "/tmp/b.json",
        )
        assert len(seeded_catalog.get_items_by_subject("econ.cpi")) == 1

    def test_insert_replaces_existing_tags(self, seeded_catalog):
        sha = "c" * 64
        seeded_catalog.insert(
            {"sha256": sha, "processed_at": 1}, "/tmp/c.json",
            subjects=[("econ.cpi", 0.8)],
        )
        seeded_catalog.insert(
            {"sha256": sha, "processed_at": 2}, "/tmp/c.json",
            subjects=[("rate.us.fed_funds", 0.8)],
        )
        assert seeded_catalog.get_items_by_subject("econ.cpi") == []
        assert len(seeded_catalog.get_items_by_subject("rate.us.fed_funds")) == 1

    def test_min_confidence_filter(self, seeded_catalog):
        now = int(time.time())
        seeded_catalog.insert(
            {"sha256": "d" * 64, "processed_at": now}, "/tmp/d.json",
            subjects=[("econ.cpi", 0.8)],
        )
        seeded_catalog.insert(
            {"sha256": "e" * 64, "processed_at": now}, "/tmp/e.json",
            subjects=[("econ.cpi", 1.0)],
        )
        low = seeded_catalog.get_items_by_subject("econ.cpi", min_confidence=0.0)
        high = seeded_catalog.get_items_by_subject("econ.cpi", min_confidence=0.9)
        assert len(low) == 2
        assert len(high) == 1

    def test_get_items_orders_by_processed_at_desc(self, seeded_catalog):
        seeded_catalog.insert(
            {"sha256": "f" * 64, "processed_at": 100}, "/tmp/f.json",
            subjects=[("econ.cpi", 0.8)],
        )
        seeded_catalog.insert(
            {"sha256": "g" * 64, "processed_at": 200}, "/tmp/g.json",
            subjects=[("econ.cpi", 0.8)],
        )
        items = seeded_catalog.get_items_by_subject("econ.cpi")
        assert items[0]["sha256"] == "g" * 64
        assert items[1]["sha256"] == "f" * 64


# ----- Golden-set regression ------------------------------------------------


class TestGoldenSet:
    """Runs the tagger against hand-tagged fixtures in tests/golden_tags.jsonl.

    For each line, the tagger's output subject set must equal the expected
    set exactly (no missing hits, no extra hits). Expand the fixture when a
    real-world false positive or negative is observed; fix the regex first.
    """

    def _cases(self):
        import json
        with GOLDEN_PATH.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                yield json.loads(line)

    def test_golden_tags_match(self, tagger):
        failures = []
        for case in self._cases():
            title = case["title"]
            expected = set(case["expected_subjects"])
            actual = {sid for sid, _ in tagger.tag_text(title)}
            if actual != expected:
                failures.append((title, sorted(expected), sorted(actual)))
        if failures:
            msg = "\n".join(
                f"  title={t!r}  expected={e}  got={g}" for t, e, g in failures
            )
            pytest.fail(f"{len(failures)} golden-tag mismatches:\n{msg}")


# ----- Backfill script ------------------------------------------------------


class TestBackfill:
    def test_backfill_tags_pre_existing_rows(self, tmp_path):
        """Items inserted before tagging are picked up by backfill_subjects."""
        import sys
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from backfill_subjects import backfill

        cat = Catalog(tmp_path / "c.db")
        # Insert untagged rows (simulating pre-tagger history).
        cat.insert(
            {"sha256": "a" * 64, "title": "CPI higher", "processed_at": 1},
            "/tmp/a.json",
        )
        cat.insert(
            {
                "sha256": "b" * 64,
                "title": "unrelated",
                "processed_at": 2,
                "subject_id": "CPIAUCSL",
            },
            "/tmp/b.json",
        )
        cat.insert(
            {"sha256": "c" * 64, "title": "quiet day", "processed_at": 3},
            "/tmp/c.json",
        )

        sync_from_yaml(cat, SEED_YAML)
        tagger = SubjectTagger(cat)

        stats = backfill(cat, tagger, dry_run=False)
        assert stats["total"] == 3
        assert stats["tagged"] == 2  # 'a' via title, 'b' via FRED series_id
        cpi_items = cat.get_items_by_subject("econ.cpi")
        shas = {it["sha256"] for it in cpi_items}
        assert shas == {"a" * 64, "b" * 64}
        cat.close()

    def test_backfill_skips_already_tagged(self, tmp_path):
        import sys
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from backfill_subjects import backfill

        cat = Catalog(tmp_path / "c.db")
        sync_from_yaml(cat, SEED_YAML)
        tagger = SubjectTagger(cat)

        cat.insert(
            {"sha256": "a" * 64, "title": "CPI higher", "processed_at": 1},
            "/tmp/a.json",
            subjects=[("econ.cpi", 0.8)],
        )
        stats = backfill(cat, tagger, dry_run=False)
        assert stats["skipped_already"] == 1
        assert stats["tagged"] == 0
        cat.close()

    def test_backfill_dry_run_writes_nothing(self, tmp_path):
        import sys
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from backfill_subjects import backfill

        cat = Catalog(tmp_path / "c.db")
        cat.insert(
            {"sha256": "a" * 64, "title": "CPI higher", "processed_at": 1},
            "/tmp/a.json",
        )
        sync_from_yaml(cat, SEED_YAML)
        tagger = SubjectTagger(cat)

        stats = backfill(cat, tagger, dry_run=True)
        assert stats["tagged"] == 1
        # No rows in item_subjects after dry-run.
        assert cat.get_items_by_subject("econ.cpi") == []
        cat.close()

    def test_run_dry_does_not_mutate_target(self, tmp_path):
        """Dry-run CLI path must not CREATE TABLE, sync vocab, or insert into
        item_subjects on the target DB.
        """
        import sqlite3
        import sys
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from backfill_subjects import run_dry

        target = tmp_path / "preexisting.db"
        # Build a pre-tagging catalog: only the items table exists, as would
        # be the case for any DB created before this branch.
        conn = sqlite3.connect(str(target))
        conn.execute(
            """CREATE TABLE items (
                sha256 TEXT PRIMARY KEY, json_path TEXT, source TEXT,
                title TEXT, subject_id TEXT, processed_at INTEGER
            )"""
        )
        conn.execute(
            "INSERT INTO items VALUES (?,?,?,?,?,?)",
            ("a" * 64, "/tmp/a.json", "news", "CPI higher", None, 1),
        )
        conn.commit()
        conn.close()

        stats = run_dry(target, SEED_YAML)
        assert stats == {"total": 1, "tagged": 1, "skipped_already": 0}

        # Verify the target DB was not altered: only `items` should exist.
        conn = sqlite3.connect(str(target))
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        conn.close()
        assert tables == {"items"}, f"dry-run created tables: {tables - {'items'}}"

    def test_run_dry_counts_pretagged_rows_as_skipped(self, tmp_path):
        """When item_subjects exists and has rows, dry-run still reads it."""
        import sys
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from backfill_subjects import run_dry

        target = tmp_path / "tagged.db"
        cat = Catalog(target)
        sync_from_yaml(cat, SEED_YAML)
        cat.insert(
            {"sha256": "a" * 64, "title": "CPI higher", "processed_at": 1},
            "/tmp/a.json",
            subjects=[("econ.cpi", 0.8)],
        )
        cat.close()

        stats = run_dry(target, SEED_YAML)
        assert stats["skipped_already"] == 1
        assert stats["tagged"] == 0
