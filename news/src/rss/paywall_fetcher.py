"""Playwright-based fetcher for paywall-protected articles.

Uses a persistent browser profile with saved login sessions to bypass
paywalls that block non-browser HTTP clients (403/401/Cloudflare).

On failure or suspected session expiry, optionally falls back to the
Internet Archive Wayback Machine before dropping to the RSS snippet.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import httpx
from readability import Document
from markdownify import markdownify

from .article_fetcher import ArticleContent

logger = logging.getLogger(__name__)


_LOGIN_URL_PATTERNS = (
    "/login", "/signin", "/sign-in", "/auth", "/subscribe",
    "/register", "/account", "/paywall",
)

_LOGIN_CONTENT_PATTERNS = (
    "subscribe to continue",
    "sign in to continue",
    "sign in to read",
    "log in to read",
    "become a subscriber",
    "this article is for subscribers",
    "create a free account",
)

_WAYBACK_AVAILABILITY_URL = "https://archive.org/wayback/available"
_WAYBACK_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class PaywallStats:
    """Per-domain counters for paywall fetch health.

    Used by the refresher / ops to decide when to rerun paywall_login.
    """
    attempts: int = 0
    playwright_ok: int = 0
    playwright_fail: int = 0
    session_expiry_suspected: int = 0
    wayback_ok: int = 0
    wayback_fail: int = 0
    rss_fallback: int = 0
    suspected_domains: set[str] = field(default_factory=set)

    def as_dict(self) -> dict:
        return {
            "attempts": self.attempts,
            "playwright_ok": self.playwright_ok,
            "playwright_fail": self.playwright_fail,
            "session_expiry_suspected": self.session_expiry_suspected,
            "wayback_ok": self.wayback_ok,
            "wayback_fail": self.wayback_fail,
            "rss_fallback": self.rss_fallback,
            "suspected_domains": sorted(self.suspected_domains),
        }


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
        wayback_fallback: bool = True,
        wayback_timeout_seconds: int = 15,
        min_content_chars: int = 500,
    ):
        self._domains = [d.lower().lstrip(".") for d in paywall_domains]
        self._browser_data_dir = str(Path(browser_data_dir).resolve())
        self._timeout_ms = timeout_ms
        self._max_content_chars = max_content_chars
        self._wayback_fallback = wayback_fallback
        self._wayback_timeout = wayback_timeout_seconds
        self._min_content_chars = min_content_chars

        # Lazy — created by _ensure_browser()
        self._playwright = None
        self._context = None

        # Lazy — created by _ensure_http_client()
        self._http: httpx.Client | None = None

        # Observability
        self.stats = PaywallStats()

    # ── Domain matching ───────────────────────────────────────

    def needs_paywall_fetch(self, url: str) -> bool:
        """Return True if *url*'s domain matches a configured paywall domain."""
        return self._matching_domain(url) is not None

    def _matching_domain(self, url: str) -> str | None:
        """Return the configured paywall domain that *url* belongs to, if any."""
        try:
            host = urlparse(url).hostname
            if not host:
                return None
            host = host.lower()
            for d in self._domains:
                if host == d or host.endswith("." + d):
                    return d
        except Exception:
            return None
        return None

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

    def _ensure_http_client(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(
                timeout=self._wayback_timeout,
                follow_redirects=True,
                headers={"User-Agent": _WAYBACK_USER_AGENT},
            )
        return self._http

    # ── Session expiry heuristics ─────────────────────────────

    @staticmethod
    def _looks_like_login_wall(final_url: str, text: str, min_chars: int) -> bool:
        """Heuristic: does this fetch look like a login/paywall redirect?

        Triggers when any of the following hold:
          - Final URL path matches a known auth/subscribe pattern.
          - Extracted text is shorter than *min_chars* AND contains a
            known paywall/login phrase.
        """
        try:
            path = (urlparse(final_url).path or "").lower()
            if any(p in path for p in _LOGIN_URL_PATTERNS):
                return True
        except Exception:
            pass

        if len(text) < min_chars:
            lowered = text.lower()
            if any(p in lowered for p in _LOGIN_CONTENT_PATTERNS):
                return True

        return False

    # ── Wayback fallback ──────────────────────────────────────

    def _try_wayback(self, url: str) -> str | None:
        """Try to fetch *url* from the Internet Archive Wayback Machine.

        Returns extracted markdown on success, None on any failure.
        """
        if not self._wayback_fallback:
            return None

        try:
            client = self._ensure_http_client()

            # 1. Ask Wayback for the closest available snapshot.
            avail = client.get(
                _WAYBACK_AVAILABILITY_URL, params={"url": url},
            )
            if avail.status_code != 200:
                return None
            data = avail.json()
            closest = (
                data.get("archived_snapshots", {}).get("closest") or {}
            )
            if not closest.get("available") or str(closest.get("status")) != "200":
                return None

            snapshot_url = closest.get("url")
            if not snapshot_url:
                return None

            # 2. Fetch the snapshot HTML and run readability over it.
            snap = client.get(snapshot_url)
            snap.raise_for_status()

            doc = Document(snap.text)
            text = markdownify(doc.summary()).strip()
            if not text:
                return None
            if len(text) > self._max_content_chars:
                text = text[: self._max_content_chars]
            return text

        except Exception as exc:
            logger.debug("Wayback fetch failed for %s: %s", url, exc)
            return None

    # ── Article fetching ──────────────────────────────────────

    def fetch_article(self, url: str, rss_description: str) -> ArticleContent:
        """Fetch *url* with headless Chromium and extract readable content.

        Order of attempts:
          1. Playwright (persistent logged-in profile).
          2. Wayback Machine snapshot (if enabled).
          3. RSS description fallback.
        """
        self.stats.attempts += 1
        matched_domain = self._matching_domain(url)

        # ── Attempt 1: Playwright ─────────────────────────────
        playwright_text: str | None = None
        playwright_error: str | None = None

        try:
            self._ensure_browser()
            page = self._context.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=self._timeout_ms)
                html = page.content()
                final_url = page.url
            finally:
                page.close()

            doc = Document(html)
            text = markdownify(doc.summary()).strip()

            if self._looks_like_login_wall(final_url, text, self._min_content_chars):
                self.stats.session_expiry_suspected += 1
                if matched_domain:
                    self.stats.suspected_domains.add(matched_domain)
                logger.warning(
                    "Paywall fetch for %s looks like a login wall "
                    "(final_url=%s, content=%d chars) — session may have expired. "
                    "Rerun: python -m src.paywall_login https://%s",
                    url, final_url, len(text),
                    matched_domain or "<domain>",
                )
                playwright_error = "suspected session expiry / login wall"
            elif text:
                playwright_text = text
            else:
                playwright_error = "readability produced empty output (playwright)"

        except Exception as exc:
            playwright_error = str(exc)
            logger.debug("Playwright paywall fetch failed for %s: %s", url, exc)

        if playwright_text is not None:
            self.stats.playwright_ok += 1
            if len(playwright_text) > self._max_content_chars:
                playwright_text = playwright_text[: self._max_content_chars]
            return ArticleContent(
                content=playwright_text,
                fetched=True,
                content_length=len(playwright_text),
            )

        self.stats.playwright_fail += 1

        # ── Attempt 2: Wayback Machine ───────────────────────
        wayback_text = self._try_wayback(url)
        if wayback_text:
            self.stats.wayback_ok += 1
            logger.info("Wayback fallback succeeded for %s", url)
            return ArticleContent(
                content=wayback_text,
                fetched=True,
                content_length=len(wayback_text),
                error=f"playwright: {playwright_error}; served via wayback",
            )
        if self._wayback_fallback:
            self.stats.wayback_fail += 1

        # ── Attempt 3: RSS description ───────────────────────
        self.stats.rss_fallback += 1
        return ArticleContent(
            content=rss_description,
            fetched=False,
            content_length=len(rss_description),
            error=playwright_error or "paywall fetch failed",
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
        """Shut down the headless browser, Playwright, and HTTP client."""
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
        if self._http is not None:
            try:
                self._http.close()
            except Exception:
                pass
            self._http = None
