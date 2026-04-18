"""IMAP-based newsletter ingestor.

Connects to a dedicated mailbox, fetches recent emails matching a set of
configured senders, runs a parser to split each email into topical
sections, and yields one news-item dict per section. The caller (NewsStream)
stores them through the same catalog / export / RAG path as RSS items.

Dedup is at the *email* level (sender + subject + YYYY-MM-DD), not the
section level — a single resend of a newsletter does not double-insert
its sections.
"""

from __future__ import annotations

import email
import hashlib
import imaplib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import quote

from .parsers import NewsletterSection, email_dedup_key, get_parser
from .state import NewsletterState

logger = logging.getLogger(__name__)


@dataclass
class SenderRule:
    """Config: which emails to pick up and how to parse them."""
    address: str              # substring-match against From:, case-insensitive
    subject_contains: str     # substring-match against Subject:, case-insensitive
    parser: str = "generic"   # parser name (see parsers.py registry)
    source: str | None = None  # override `source` field for stored items


@dataclass
class NewsletterItem:
    """One stored unit (one section of one email)."""
    item_id: str
    source: str
    title: str
    description: str
    link: str
    published: str
    fetched_at: str
    feed_category: str


class NewsletterProvider:
    """Fetch, parse, and dedup newsletter emails over IMAP."""

    provider_name = "newsletter"

    def __init__(
        self,
        imap_host: str,
        imap_user: str,
        imap_password: str,
        sender_rules: list[SenderRule],
        state: NewsletterState,
        *,
        imap_port: int = 993,
        mailbox: str = "INBOX",
        lookback_days: int = 7,
        max_section_chars: int = 15_000,
        timeout_seconds: int = 30,
    ):
        self._host = imap_host
        self._port = imap_port
        self._user = imap_user
        self._password = imap_password
        self._mailbox = mailbox
        self._rules = sender_rules
        self._state = state
        self._lookback_days = lookback_days
        self._max_section_chars = max_section_chars
        self._timeout = timeout_seconds

    # ── Public API ────────────────────────────────────────────

    def fetch(self) -> list[NewsletterItem]:
        """Connect, fetch, parse, and dedup. Return new items only.

        Never raises on a per-email failure — logs and moves on.
        """
        try:
            conn = self._connect()
        except Exception as exc:
            logger.warning("IMAP connect failed for %s@%s: %s",
                           self._user, self._host, exc)
            return []

        try:
            raw_messages = self._fetch_recent(conn)
        finally:
            try:
                conn.logout()
            except Exception:
                pass

        items: list[NewsletterItem] = []
        for msg in raw_messages:
            items.extend(self._process_message(msg))

        logger.info(
            "Newsletter provider: %d emails scanned, %d sections stored",
            len(raw_messages), len(items),
        )
        return items

    # ── IMAP plumbing ─────────────────────────────────────────

    def _connect(self) -> imaplib.IMAP4_SSL:
        conn = imaplib.IMAP4_SSL(self._host, self._port, timeout=self._timeout)
        conn.login(self._user, self._password)
        conn.select(self._mailbox, readonly=True)
        return conn

    def _fetch_recent(self, conn: imaplib.IMAP4_SSL) -> list[email.message.Message]:
        """Return messages newer than *lookback_days* that match any sender rule."""
        since = (datetime.now(timezone.utc) - timedelta(days=self._lookback_days)).strftime(
            "%d-%b-%Y"
        )

        # Build a SEARCH query per sender to cut server-side work.
        messages: dict[bytes, email.message.Message] = {}
        for rule in self._rules:
            status, data = conn.search(
                None, "SINCE", since, "FROM", f'"{rule.address}"',
            )
            if status != "OK" or not data or not data[0]:
                continue
            for uid in data[0].split():
                if uid in messages:
                    continue
                fetch_status, fetch_data = conn.fetch(uid, "(RFC822)")
                if fetch_status != "OK" or not fetch_data or not fetch_data[0]:
                    continue
                raw = fetch_data[0][1]
                if not isinstance(raw, (bytes, bytearray)):
                    continue
                try:
                    msg = email.message_from_bytes(raw)
                except Exception as exc:
                    logger.debug("email parse failed uid=%s: %s", uid, exc)
                    continue
                messages[uid] = msg

        return list(messages.values())

    # ── Per-message processing ────────────────────────────────

    def _process_message(self, msg: email.message.Message) -> list[NewsletterItem]:
        subject = _decode(msg.get("Subject", ""))
        from_raw = _decode(msg.get("From", ""))
        sender_addr = _extract_address(from_raw)
        date_iso = _parse_email_date(msg.get("Date", ""))

        rule = self._match_rule(sender_addr, subject)
        if rule is None:
            return []

        dedup_key = email_dedup_key(sender_addr, subject, date_iso)
        if self._state.has(dedup_key):
            logger.debug("Skipping already-processed email %s: %s",
                         dedup_key, subject[:60])
            return []

        html, text = _extract_bodies(msg)
        if not html and not text:
            logger.debug("Email has no usable body: %s", subject[:60])
            self._state.record(dedup_key, sender_addr, subject, date_iso)
            return []

        parser = get_parser(rule.parser)
        sections = parser(html, text, self._max_section_chars)
        if not sections:
            self._state.record(dedup_key, sender_addr, subject, date_iso)
            return []

        items = self._build_items(rule, sender_addr, subject, date_iso, sections)
        # Only record after successful build — if build raises, we retry next cycle
        self._state.record(dedup_key, sender_addr, subject, date_iso)
        return items

    def _match_rule(self, sender: str, subject: str) -> SenderRule | None:
        s_lower = sender.lower()
        subj_lower = subject.lower()
        for rule in self._rules:
            if rule.address.lower() not in s_lower:
                continue
            if rule.subject_contains and rule.subject_contains.lower() not in subj_lower:
                continue
            return rule
        return None

    def _build_items(
        self,
        rule: SenderRule,
        sender: str,
        subject: str,
        date_iso: str,
        sections: Iterable[NewsletterSection],
    ) -> list[NewsletterItem]:
        now_iso = datetime.now(timezone.utc).isoformat()
        source = rule.source or f"newsletter:{_domain_of(sender) or sender}"
        subject_slug = _slug(subject)
        date_slug = (date_iso or now_iso)[:10]

        items: list[NewsletterItem] = []
        for section in sections:
            link = (
                f"mailto://{_domain_of(sender) or 'newsletter'}"
                f"/{quote(subject_slug)}/{date_slug}#{section.anchor}"
            )
            item_id = hashlib.sha256(link.encode("utf-8")).hexdigest()[:16]
            title = (
                f"{subject}: {section.title}" if section.title else subject
            )
            items.append(NewsletterItem(
                item_id=item_id,
                source=source,
                title=title,
                description=section.content,
                link=link,
                published=date_iso or now_iso,
                fetched_at=now_iso,
                feed_category="newsletter",
            ))
        return items


# ── Helpers ────────────────────────────────────────────────────


def _decode(value: str) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _extract_address(from_field: str) -> str:
    pairs = getaddresses([from_field or ""])
    if pairs:
        return pairs[0][1] or ""
    return ""


def _parse_email_date(raw: str) -> str:
    if not raw:
        return ""
    try:
        dt = parsedate_to_datetime(raw)
        if dt is None:
            return ""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except Exception:
        return ""


def _extract_bodies(msg: email.message.Message) -> tuple[str, str]:
    """Return (html, text) bodies from a possibly multipart email."""
    html_parts: list[str] = []
    text_parts: list[str] = []

    if msg.is_multipart():
        for part in msg.walk():
            if part.is_multipart():
                continue
            ctype = part.get_content_type()
            disp = (part.get("Content-Disposition") or "").lower()
            if "attachment" in disp:
                continue
            charset = part.get_content_charset() or "utf-8"
            try:
                payload = part.get_payload(decode=True)
            except Exception:
                continue
            if payload is None:
                continue
            try:
                decoded = payload.decode(charset, errors="replace")
            except LookupError:
                decoded = payload.decode("utf-8", errors="replace")
            if ctype == "text/html":
                html_parts.append(decoded)
            elif ctype == "text/plain":
                text_parts.append(decoded)
    else:
        charset = msg.get_content_charset() or "utf-8"
        try:
            payload = msg.get_payload(decode=True)
        except Exception:
            payload = None
        if payload is not None:
            try:
                decoded = payload.decode(charset, errors="replace")
            except LookupError:
                decoded = payload.decode("utf-8", errors="replace")
            if msg.get_content_type() == "text/html":
                html_parts.append(decoded)
            else:
                text_parts.append(decoded)

    return ("\n".join(html_parts).strip(), "\n".join(text_parts).strip())


def _domain_of(address: str) -> str:
    if not address or "@" not in address:
        return ""
    return address.rsplit("@", 1)[-1].strip().lower()


def _slug(text: str, max_len: int = 60) -> str:
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:max_len] or "email"
