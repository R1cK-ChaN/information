"""Tests for the headline deduplicator."""

from src.deduplicator import Deduplicator, _tokenize, _jaccard_similarity


class TestTokenize:
    def test_basic(self):
        tokens = _tokenize("Fed raises interest rates by 25 basis points")
        assert "raises" in tokens
        assert "interest" in tokens
        assert "rates" in tokens
        assert "basis" in tokens
        assert "points" in tokens
        # Short words / stopwords removed
        assert "by" not in tokens
        assert "25" not in tokens  # len <= 2

    def test_punctuation_removed(self):
        tokens = _tokenize("U.S. economy's growth slows!")
        assert "economy" not in tokens  # "economys" after removing punct? let's check
        # Actually "economy's" -> "economys" -> included if > 2 chars
        assert "growth" in tokens
        assert "slows" in tokens

    def test_stopwords_removed(self):
        tokens = _tokenize("The market is going up again")
        assert "the" not in tokens
        assert "is" not in tokens
        assert "again" not in tokens
        assert "market" in tokens
        assert "going" in tokens

    def test_empty_string(self):
        assert _tokenize("") == set()


class TestJaccardSimilarity:
    def test_identical(self):
        s = {"fed", "raises", "rates"}
        assert _jaccard_similarity(s, s) == 1.0

    def test_disjoint(self):
        a = {"fed", "raises", "rates"}
        b = {"gold", "price", "surges"}
        assert _jaccard_similarity(a, b) == 0.0

    def test_partial_overlap(self):
        a = {"fed", "raises", "interest", "rates"}
        b = {"fed", "cuts", "interest", "rates"}
        sim = _jaccard_similarity(a, b)
        # intersection: {fed, interest, rates} = 3, min(4,4)=4 → 0.75
        assert sim == 0.75

    def test_empty_sets(self):
        assert _jaccard_similarity(set(), {"a", "b"}) == 0.0
        assert _jaccard_similarity(set(), set()) == 0.0


class TestDeduplicator:
    def test_first_is_never_duplicate(self):
        d = Deduplicator()
        assert not d.is_duplicate("Fed raises interest rates")

    def test_exact_duplicate(self):
        d = Deduplicator()
        d.is_duplicate("Fed raises interest rates by 25 basis points")
        assert d.is_duplicate("Fed raises interest rates by 25 basis points")

    def test_similar_duplicate(self):
        d = Deduplicator()
        d.is_duplicate("Fed raises interest rates by 25 basis points")
        # Very similar headline
        assert d.is_duplicate("Federal Reserve raises interest rates 25 basis points")

    def test_different_headline_passes(self):
        d = Deduplicator()
        d.is_duplicate("Fed raises interest rates by 25 basis points")
        assert not d.is_duplicate("Gold price surges to record high amid uncertainty")

    def test_filter_returns_unique(self):
        d = Deduplicator()
        titles = [
            "Fed raises interest rates by 25 basis points",
            "Federal Reserve raises interest rates 25 points",
            "Gold price surges to record high amid market uncertainty",
            "Gold price surges to record high on market uncertainty",
            "Bitcoin drops below $30,000",
        ]
        unique = d.filter(titles)
        assert len(unique) == 3

    def test_seed_from_existing(self):
        d = Deduplicator()
        d.seed(["Fed raises interest rates by 25 basis points"])
        assert d.seen_count == 1
        assert d.is_duplicate("Fed raises interest rates 25 basis points")

    def test_threshold_configurable(self):
        d = Deduplicator(threshold=0.9)
        d.is_duplicate("Fed raises interest rates by 25 basis points")
        # With higher threshold, similar but not identical should pass
        assert not d.is_duplicate("Fed cuts interest rates by 50 basis points")

    def test_reset(self):
        d = Deduplicator()
        d.is_duplicate("Some headline here")
        assert d.seen_count == 1
        d.reset()
        assert d.seen_count == 0

    def test_empty_title_is_duplicate(self):
        d = Deduplicator()
        assert d.is_duplicate("")
