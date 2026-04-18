"""Email newsletter ingestion (IMAP) for subscriber-only content.

Captures Bloomberg Opinion, FT Lex, WSJ, and other publisher newsletters
that ship full column bodies directly to the subscriber's inbox — content
that plain RSS / paywall scraping cannot reach.
"""

from .provider import NewsletterProvider, NewsletterItem
from .parsers import NewsletterSection, get_parser, register_parser

__all__ = [
    "NewsletterProvider",
    "NewsletterItem",
    "NewsletterSection",
    "get_parser",
    "register_parser",
]
