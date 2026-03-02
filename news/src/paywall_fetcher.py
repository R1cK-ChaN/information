"""Playwright-based fetcher for paywall-protected articles.

Uses a persistent browser profile with saved login sessions to bypass
paywalls that block non-browser HTTP clients (403/401/Cloudflare).
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlparse

from readability import Document
from markdownify import markdownify

from .article_fetcher import ArticleContent

logger = logging.getLogger(__name__)


class PaywallFetcher:
    """Fetch articles from paywall-protected domains via headless Chromium.

    The browser is lazily initialised on the first call to fetch_article()
    and stays alive for the duration of a refresh cycle.  Call close()
    when done.
    """

    def __init__(
        self,
        paywall_domains: list[str],
        browser_data_dir: str | Path = "data/browser_profile",
        timeout_ms: int = 30_000,
        max_content_chars: int = 15_000,
    ):
        self._domains = [d.lower().lstrip(".") for d in paywall_domains]
        self._browser_data_dir = str(Path(browser_data_dir).resolve())
        self._timeout_ms = timeout_ms
        self._max_content_chars = max_content_chars

        # Lazy — created by _ensure_browser()
        self._playwright = None
        self._context = None

    # ── Domain matching ───────────────────────────────────────

    def needs_paywall_fetch(self, url: str) -> bool:
        """Return True if *url*'s domain matches a configured paywall domain."""
        try:
            host = urlparse(url).hostname
            if not host:
                return False
            host = host.lower()
            return any(
                host == d or host.endswith("." + d) for d in self._domains
            )
        except Exception:
            return False

    # ── Browser lifecycle ─────────────────────────────────────

    def _ensure_browser(self) -> None:
        """Lazily start Playwright + persistent Chromium context."""
        if self._context is not None:
            return

        from playwright.sync_api import sync_playwright  # noqa: late import

        self._playwright = sync_playwright().start()
        self._context = self._playwright.chromium.launch_persistent_context(
            self._browser_data_dir,
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )

    # ── Article fetching ──────────────────────────────────────

    def fetch_article(self, url: str, rss_description: str) -> ArticleContent:
        """Fetch *url* with headless Chromium and extract readable content.

        Falls back to *rss_description* on any failure.
        """
        try:
            self._ensure_browser()
            page = self._context.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=self._timeout_ms)
                html = page.content()
            finally:
                page.close()

            doc = Document(html)
            text = markdownify(doc.summary()).strip()

            if not text:
                return ArticleContent(
                    content=rss_description,
                    fetched=False,
                    content_length=len(rss_description),
                    error="readability produced empty output (playwright)",
                )

            if len(text) > self._max_content_chars:
                text = text[: self._max_content_chars]

            return ArticleContent(
                content=text,
                fetched=True,
                content_length=len(text),
            )

        except Exception as exc:
            logger.debug("Paywall fetch failed for %s: %s", url, exc)
            return ArticleContent(
                content=rss_description,
                fetched=False,
                content_length=len(rss_description),
                error=str(exc),
            )

    # ── Manual login ──────────────────────────────────────────

    def login(self, url: str) -> None:
        """Open a VISIBLE browser with the persistent profile for manual login.

        Blocks until the user closes the browser window.
        """
        from playwright.sync_api import sync_playwright  # noqa: late import

        pw = sync_playwright().start()
        try:
            context = pw.chromium.launch_persistent_context(
                self._browser_data_dir,
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            print(f"Browser opened to {url}")
            print("Log in, then close the browser window to save the session.")
            # Block until the user closes the browser
            context.pages[0].wait_for_event("close", timeout=0)
            context.close()
        finally:
            pw.stop()

    # ── Cleanup ───────────────────────────────────────────────

    def close(self) -> None:
        """Shut down the headless browser and Playwright, if running."""
        if self._context is not None:
            try:
                self._context.close()
            except Exception:
                pass
            self._context = None
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
