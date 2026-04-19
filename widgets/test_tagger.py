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
        assert "econ.us.cpi" in ids
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
        cpi_aliases = seeded_catalog.get_aliases("econ.us.cpi", "fred_series")
        assert "CPIAUCSL" in cpi_aliases

    def test_sync_is_idempotent(self, seeded_catalog):
        sync_from_yaml(seeded_catalog, SEED_YAML)
        sync_from_yaml(seeded_catalog, SEED_YAML)
        assert len(seeded_catalog.list_subjects()) == 20


# ----- Tagger: structured ---------------------------------------------------


class TestTagStructured:
    def test_fred_series_exact_match(self, tagger):
        tags = tagger.tag_fred_series("CPIAUCSL")
        assert tags == [("econ.us.cpi", 1.0)]

    def test_fred_series_case_insensitive(self, tagger):
        tags = tagger.tag_fred_series("cpiaucsl")
        assert tags == [("econ.us.cpi", 1.0)]

    def test_fred_series_unknown_returns_empty(self, tagger):
        assert tagger.tag_fred_series("UNKNOWN_SERIES_XYZ") == []

    def test_fred_series_multiple(self, tagger):
        tags = tagger.tag_fred_series(["CPIAUCSL", "FEDFUNDS"])
        sids = {t[0] for t in tags}
        assert sids == {"econ.us.cpi", "rate.us.fed_funds"}
        assert all(conf == 1.0 for _, conf in tags)

    def test_calendar_indicator_case_insensitive(self, tagger):
        assert tagger.tag_calendar_indicator("CPI") == [("econ.us.cpi", 1.0)]
        assert tagger.tag_calendar_indicator("cpi") == [("econ.us.cpi", 1.0)]

    def test_calendar_indicator_multi_word(self, tagger):
        tags = tagger.tag_calendar_indicator("Nonfarm Payrolls")
        assert tags == [("econ.us.nfp", 1.0)]

    def test_tag_structured_combines(self, tagger):
        tags = tagger.tag_structured(
            fred_series="PAYEMS", calendar_indicator="CPI"
        )
        sids = {t[0] for t in tags}
        assert sids == {"econ.us.nfp", "econ.us.cpi"}


# ----- Tagger: text ---------------------------------------------------------


class TestTagText:
    def test_exact_cpi_match(self, tagger):
        tags = tagger.tag_text("US CPI ticks higher in June")
        sids = {t[0] for t in tags}
        assert "econ.us.cpi" in sids

    def test_consumer_price_phrase(self, tagger):
        tags = tagger.tag_text("Consumer prices ease in Europe")
        sids = {t[0] for t in tags}
        assert "econ.us.cpi" in sids

    def test_multi_subject_title(self, tagger):
        tags = tagger.tag_text("FOMC hikes 25bp after hot CPI print")
        sids = {t[0] for t in tags}
        assert "econ.us.cpi" in sids
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
            result, "/tmp/t.json", subjects=[("econ.us.cpi", 0.8)]
        )
        items = seeded_catalog.get_items_by_subject("econ.us.cpi")
        assert len(items) == 1
        assert items[0]["sha256"] == "a" * 64
        assert items[0]["subject_confidence"] == 0.8

    def test_insert_with_subjects_none_leaves_join_untouched(self, seeded_catalog):
        sha = "b" * 64
        seeded_catalog.insert(
            {"sha256": sha, "processed_at": 1}, "/tmp/b.json",
            subjects=[("econ.us.cpi", 0.8)],
        )
        # Second insert without subjects kwarg must NOT clear the tags.
        seeded_catalog.insert(
            {"sha256": sha, "processed_at": 2, "title": "updated"},
            "/tmp/b.json",
        )
        assert len(seeded_catalog.get_items_by_subject("econ.us.cpi")) == 1

    def test_insert_replaces_existing_tags(self, seeded_catalog):
        sha = "c" * 64
        seeded_catalog.insert(
            {"sha256": sha, "processed_at": 1}, "/tmp/c.json",
            subjects=[("econ.us.cpi", 0.8)],
        )
        seeded_catalog.insert(
            {"sha256": sha, "processed_at": 2}, "/tmp/c.json",
            subjects=[("rate.us.fed_funds", 0.8)],
        )
        assert seeded_catalog.get_items_by_subject("econ.us.cpi") == []
        assert len(seeded_catalog.get_items_by_subject("rate.us.fed_funds")) == 1

    def test_min_confidence_filter(self, seeded_catalog):
        now = int(time.time())
        seeded_catalog.insert(
            {"sha256": "d" * 64, "processed_at": now}, "/tmp/d.json",
            subjects=[("econ.us.cpi", 0.8)],
        )
        seeded_catalog.insert(
            {"sha256": "e" * 64, "processed_at": now}, "/tmp/e.json",
            subjects=[("econ.us.cpi", 1.0)],
        )
        low = seeded_catalog.get_items_by_subject("econ.us.cpi", min_confidence=0.0)
        high = seeded_catalog.get_items_by_subject("econ.us.cpi", min_confidence=0.9)
        assert len(low) == 2
        assert len(high) == 1

    def test_get_items_orders_by_processed_at_desc(self, seeded_catalog):
        seeded_catalog.insert(
            {"sha256": "f" * 64, "processed_at": 100}, "/tmp/f.json",
            subjects=[("econ.us.cpi", 0.8)],
        )
        seeded_catalog.insert(
            {"sha256": "g" * 64, "processed_at": 200}, "/tmp/g.json",
            subjects=[("econ.us.cpi", 0.8)],
        )
        items = seeded_catalog.get_items_by_subject("econ.us.cpi")
        assert items[0]["sha256"] == "g" * 64
        assert items[1]["sha256"] == "f" * 64
