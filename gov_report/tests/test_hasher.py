"""Tests for hasher module."""

from gov_report.hasher import content_sha


def test_content_sha_deterministic():
    sha1 = content_sha("https://example.com/report", "2025-01-15")
    sha2 = content_sha("https://example.com/report", "2025-01-15")
    assert sha1 == sha2
    assert len(sha1) == 64  # hex sha256


def test_content_sha_different_url():
    sha1 = content_sha("https://example.com/report-a", "2025-01-15")
    sha2 = content_sha("https://example.com/report-b", "2025-01-15")
    assert sha1 != sha2


def test_content_sha_different_date():
    sha1 = content_sha("https://example.com/report", "2025-01-15")
    sha2 = content_sha("https://example.com/report", "2025-02-15")
    assert sha1 != sha2
