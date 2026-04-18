"""Tests for the newsletter module.

Covers:
 - generic parser behaviour (splits on h1/h2/h3; single-section fallback)
 - email_dedup_key stability
 - NewsletterState round-trip
 - NewsletterProvider happy path with IMAP stubbed
 - Sender-rule mismatch (skipped)
 - Loose dedup (second run of same email yields zero items)
"""

from __future__ import annotations

from email.message import EmailMessage

import pytest

from src.newsletter.parsers import (
    email_dedup_key,
    generic_parser,
    get_parser,
)
from src.newsletter.provider import NewsletterProvider, SenderRule
from src.newsletter.state import NewsletterState


# ─── Parser ─────────────────────────────────────────────────────


def test_generic_parser_splits_on_h2():
    html = """
    <html><body>
      <h2>First Topic</h2>
      <p>Alpha body content that is long enough to count as real.</p>
      <h2>Second Topic</h2>
      <p>Beta body content, also substantive.</p>
    </body></html>
    """
    sections = generic_parser(html, "", max_section_chars=1000)
    assert len(sections) == 2
    assert sections[0].title == "First Topic"
    assert "Alpha" in sections[0].content
    assert sections[1].title == "Second Topic"
    assert "Beta" in sections[1].content
    # Anchors distinct
    assert sections[0].anchor != sections[1].anchor


def test_generic_parser_single_section_when_no_headers():
    html = "<html><body><p>Just a long body with no headers at all.</p></body></html>"
    sections = generic_parser(html, "", max_section_chars=1000)
    assert len(sections) == 1
    assert sections[0].title == ""
    assert "long body" in sections[0].content


def test_generic_parser_plain_text_fallback():
    sections = generic_parser("", "plain text only\n\nsome body", max_section_chars=100)
    assert len(sections) == 1
    assert "plain text" in sections[0].content


def test_generic_parser_empty_returns_empty():
    assert generic_parser("", "", 100) == []


def test_generic_parser_truncates_at_max_chars():
    html = "<html><body><h2>T</h2><p>" + ("x" * 200) + "</p></body></html>"
    sections = generic_parser(html, "", max_section_chars=50)
    assert sections
    assert len(sections[0].content) <= 50


def test_get_parser_falls_back_to_generic():
    assert get_parser("nonexistent_parser_name") is generic_parser


def test_email_dedup_key_stable_across_calls():
    a = email_dedup_key("alice@ex.com", "Daily Brief", "2026-04-18T10:00:00+00:00")
    b = email_dedup_key("ALICE@ex.com", "  Daily Brief  ", "2026-04-18T12:00:00+00:00")
    # Same calendar day + sender + subject -> same key
    assert a == b


def test_email_dedup_key_differs_by_day():
    a = email_dedup_key("alice@ex.com", "Daily Brief", "2026-04-18T10:00:00+00:00")
    b = email_dedup_key("alice@ex.com", "Daily Brief", "2026-04-19T10:00:00+00:00")
    assert a != b


# ─── State ──────────────────────────────────────────────────────


def test_state_roundtrip(tmp_path):
    state = NewsletterState(tmp_path / "state.db")
    key = "abc123"
    assert state.has(key) is False
    state.record(key, "x@y.com", "Subject", "2026-04-18T10:00:00+00:00")
    assert state.has(key) is True
    assert state.count() == 1
    # Idempotent
    state.record(key, "x@y.com", "Subject", "2026-04-18T10:00:00+00:00")
    assert state.count() == 1
    state.close()


# ─── Provider ───────────────────────────────────────────────────


def _build_email(sender: str, subject: str, html: str, date: str) -> bytes:
    msg = EmailMessage()
    msg["From"] = sender
    msg["Subject"] = subject
    msg["Date"] = date
    msg.set_content("plain fallback", subtype="plain")
    msg.add_alternative(html, subtype="html")
    return msg.as_bytes()


class _FakeIMAP:
    """Minimal stub of imaplib.IMAP4_SSL for provider tests."""

    def __init__(self, messages: dict[bytes, bytes]):
        self._messages = messages
        self._selected = False

    def login(self, user, password):
        return ("OK", [b""])

    def select(self, mailbox, readonly=False):
        self._selected = True
        return ("OK", [b""])

    def search(self, charset, *criteria):
        # Return all uids regardless of criteria — per-rule filtering is
        # still exercised via the provider's match_rule logic.
        return ("OK", [b" ".join(self._messages.keys())])

    def fetch(self, uid, spec):
        raw = self._messages.get(uid)
        if raw is None:
            return ("NO", [])
        return ("OK", [(uid, raw)])

    def logout(self):
        return ("BYE", [b""])


@pytest.fixture
def fake_imap_factory(monkeypatch):
    """Install a factory that returns a preset _FakeIMAP for IMAP4_SSL()."""
    holder: dict = {"fake": None}

    def install(messages: dict[bytes, bytes]) -> None:
        holder["fake"] = _FakeIMAP(messages)

        def _factory(*args, **kwargs):
            return holder["fake"]

        import imaplib
        monkeypatch.setattr(imaplib, "IMAP4_SSL", _factory)

    return install


def test_provider_happy_path(tmp_path, fake_imap_factory):
    html = """
    <html><body>
      <h2>Policy Debate</h2>
      <p>Fed officials discussed rate path. Substantive commentary here.</p>
      <h2>Markets</h2>
      <p>Equities slipped on the session.</p>
    </body></html>
    """
    raw = _build_email(
        sender="Bloomberg <noreply@news.bloomberg.com>",
        subject="Money Stuff: Rates and Equities",
        html=html,
        date="Fri, 18 Apr 2026 10:00:00 +0000",
    )
    fake_imap_factory({b"1": raw})

    state = NewsletterState(tmp_path / "state.db")
    provider = NewsletterProvider(
        imap_host="imap.example.com",
        imap_user="me@example.com",
        imap_password="secret",
        sender_rules=[SenderRule(
            address="noreply@news.bloomberg.com",
            subject_contains="Money Stuff",
        )],
        state=state,
        lookback_days=7,
    )

    items = provider.fetch()
    assert len(items) == 2

    # Links share stem, differ on anchor
    links = [item.link for item in items]
    assert links[0] != links[1]
    assert all(link.startswith("mailto://news.bloomberg.com/") for link in links)
    assert "#" in links[0]

    # Title prefixes subject
    assert items[0].title.startswith("Money Stuff: Rates and Equities")
    assert items[0].feed_category == "newsletter"
    assert items[0].source.startswith("newsletter:")

    # Second run: same email -> zero new items (loose dedup)
    items2 = provider.fetch()
    assert items2 == []

    state.close()


def test_provider_skips_unmatched_sender(tmp_path, fake_imap_factory):
    raw = _build_email(
        sender="someone-else@random.com",
        subject="Some Newsletter",
        html="<p>body</p>",
        date="Fri, 18 Apr 2026 10:00:00 +0000",
    )
    fake_imap_factory({b"1": raw})

    state = NewsletterState(tmp_path / "state.db")
    provider = NewsletterProvider(
        imap_host="imap.example.com",
        imap_user="me@example.com",
        imap_password="secret",
        sender_rules=[SenderRule(
            address="noreply@news.bloomberg.com",
            subject_contains="Money Stuff",
        )],
        state=state,
    )

    # Provider's IMAP search returns the message; rule matching rejects it.
    items = provider.fetch()
    assert items == []
    state.close()


def test_provider_subject_contains_filter(tmp_path, fake_imap_factory):
    raw_match = _build_email(
        sender="noreply@news.bloomberg.com",
        subject="Money Stuff: Something",
        html="<h2>T</h2><p>body body body</p>",
        date="Fri, 18 Apr 2026 10:00:00 +0000",
    )
    raw_skip = _build_email(
        sender="noreply@news.bloomberg.com",
        subject="Evening Briefing",
        html="<h2>T</h2><p>body body body</p>",
        date="Fri, 18 Apr 2026 10:00:00 +0000",
    )
    fake_imap_factory({b"1": raw_match, b"2": raw_skip})

    state = NewsletterState(tmp_path / "state.db")
    provider = NewsletterProvider(
        imap_host="imap.example.com",
        imap_user="me@example.com",
        imap_password="secret",
        sender_rules=[SenderRule(
            address="noreply@news.bloomberg.com",
            subject_contains="Money Stuff",
        )],
        state=state,
    )

    items = provider.fetch()
    # Only the Money Stuff email produces a section
    assert len(items) == 1
    assert "Money Stuff" in items[0].title
    state.close()
