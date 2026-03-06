"""Headline deduplication using Jaccard word-overlap similarity."""

import re

# Common English stopwords to filter out
_STOPWORDS = frozenset([
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "has", "have", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "not", "no", "nor", "so",
    "if", "then", "than", "too", "very", "just", "about", "up", "out",
    "its", "it", "this", "that", "these", "those", "he", "she", "they",
    "his", "her", "their", "our", "your", "my", "we", "you", "me",
    "him", "them", "us", "who", "what", "when", "where", "how", "which",
    "all", "each", "every", "both", "few", "more", "most", "other",
    "some", "such", "only", "own", "same", "into", "over", "after",
    "before", "between", "under", "again", "once", "here", "there",
    "why", "also", "new", "says", "said",
])

_PUNCT_RE = re.compile(r"[^\w\s]")
_SPACE_RE = re.compile(r"\s+")


def _tokenize(text: str) -> set[str]:
    """Normalize and tokenize a headline into a word set."""
    cleaned = _PUNCT_RE.sub("", text.lower())
    cleaned = _SPACE_RE.sub(" ", cleaned).strip()
    return {w for w in cleaned.split() if len(w) > 2 and w not in _STOPWORDS}


def _jaccard_similarity(a: set[str], b: set[str]) -> float:
    """Jaccard-like similarity using min-denominator (matches worldmonitor)."""
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    return intersection / min(len(a), len(b))


class Deduplicator:
    """Stateful headline deduplicator using word-overlap similarity."""

    def __init__(self, threshold: float = 0.6):
        self.threshold = threshold
        self._seen: list[set[str]] = []

    def seed(self, titles: list[str]):
        """Pre-seed with existing titles (e.g., from last 24h in storage)."""
        for title in titles:
            tokens = _tokenize(title)
            if tokens:
                self._seen.append(tokens)

    def is_duplicate(self, title: str) -> bool:
        """Check if a title is a duplicate of any seen title."""
        tokens = _tokenize(title)
        if not tokens:
            return True  # empty titles are considered duplicates

        for seen_tokens in self._seen:
            if _jaccard_similarity(tokens, seen_tokens) > self.threshold:
                return True

        self._seen.append(tokens)
        return False

    def filter(self, titles: list[str]) -> list[str]:
        """Return only unique titles from a list."""
        return [t for t in titles if not self.is_duplicate(t)]

    def reset(self):
        """Clear all seen titles."""
        self._seen.clear()

    @property
    def seen_count(self) -> int:
        return len(self._seen)
