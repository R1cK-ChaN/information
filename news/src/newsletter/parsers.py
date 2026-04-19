"""Newsletter section parsers.

Each parser receives the email's (raw_html, raw_text) and returns a list
of NewsletterSection objects — one per topical unit within the email.

The generic parser splits on <h1>/<h2>/<h3> headers. Per-sender parsers
can be registered for newsletters whose template doesn't fit the generic
pattern (e.g. if a publisher uses tables or class-based markers).
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from typing import Callable

from bs4 import BeautifulSoup
from markdownify import markdownify

from ..discovery import extract_urls

logger = logging.getLogger(__name__)


@dataclass
class NewsletterSection:
    """One topical unit within a newsletter email."""
    anchor: str      # URL-safe section identifier, e.g. "money-stuff-2"
    title: str       # section heading (may be empty for single-section fallback)
    content: str     # markdown body
    references: list[str] = None  # external URLs called out in the body

    def __post_init__(self) -> None:
        if self.references is None:
            self.references = extract_urls(self.content, limit=20)


_ANCHOR_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str, max_len: int = 50) -> str:
    slug = _ANCHOR_SLUG_RE.sub("-", text.lower()).strip("-")
    return slug[:max_len] or "section"


def _anchor_from(title: str, index: int) -> str:
    """Build a stable anchor from a section title, falling back to index."""
    if title:
        return f"{_slugify(title)}-{index}"
    return f"section-{index}"


def generic_parser(
    raw_html: str,
    raw_text: str,
    max_section_chars: int = 15_000,
) -> list[NewsletterSection]:
    """Split a newsletter email into sections on h1/h2/h3 headers.

    Works for most publisher newsletters (Bloomberg, FT, WSJ templates
    all use heading tags for topical breaks).

    If no headers are found, returns a single section containing the
    whole email body.
    """
    soup = BeautifulSoup(raw_html or "", "html.parser") if raw_html else None

    if soup is None or not (raw_html and raw_html.strip()):
        # Plain-text fallback
        text = (raw_text or "").strip()
        if not text:
            return []
        if len(text) > max_section_chars:
            text = text[:max_section_chars]
        return [NewsletterSection(anchor="section-0", title="", content=text)]

    headers = soup.find_all(["h1", "h2", "h3"])

    if not headers:
        # No structure — return the whole email as one section
        content = markdownify(str(soup)).strip()
        if not content and raw_text:
            content = raw_text.strip()
        if len(content) > max_section_chars:
            content = content[:max_section_chars]
        if not content:
            return []
        return [NewsletterSection(anchor="section-0", title="", content=content)]

    sections: list[NewsletterSection] = []

    for idx, header in enumerate(headers):
        title = header.get_text(strip=True)
        if not title:
            continue

        # Collect siblings until the next header
        body_parts: list[str] = []
        sibling = header.next_sibling
        while sibling is not None:
            # Stop at the next header at same-or-higher level
            name = getattr(sibling, "name", None)
            if name in ("h1", "h2", "h3"):
                break
            if hasattr(sibling, "__str__"):
                body_parts.append(str(sibling))
            sibling = sibling.next_sibling

        body_html = "".join(body_parts).strip()
        body_md = markdownify(body_html).strip() if body_html else ""

        if not body_md:
            # Skip empty sections (e.g. a header followed immediately by another header)
            continue

        if len(body_md) > max_section_chars:
            body_md = body_md[:max_section_chars]

        sections.append(NewsletterSection(
            anchor=_anchor_from(title, idx),
            title=title,
            content=body_md,
        ))

    if not sections:
        # Headers existed but nothing usable — fall back to whole-body single section
        content = markdownify(str(soup)).strip()
        if len(content) > max_section_chars:
            content = content[:max_section_chars]
        if content:
            return [NewsletterSection(anchor="section-0", title="", content=content)]

    return sections


# ── Parser registry ─────────────────────────────────────────────────────

ParserFn = Callable[[str, str, int], list[NewsletterSection]]

_REGISTRY: dict[str, ParserFn] = {
    "generic": generic_parser,
}


def register_parser(name: str, fn: ParserFn) -> None:
    """Register a per-sender parser under *name*."""
    _REGISTRY[name] = fn


def get_parser(name: str) -> ParserFn:
    """Look up a parser by name, falling back to generic if not found."""
    return _REGISTRY.get(name, generic_parser)


# ── Email-level dedup key ───────────────────────────────────────────────


def email_dedup_key(sender: str, subject: str, date_iso: str) -> str:
    """Loose dedup key: sha256(sender + subject + date).

    Dates are normalised to YYYY-MM-DD so that resends (which typically
    arrive within the same calendar day) collapse into one key.
    """
    day = (date_iso or "")[:10]
    raw = f"{sender.lower()}|{subject.strip().lower()}|{day}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
