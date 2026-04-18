"""Tests for PaywallFetcher: Wayback fallback and session-expiry detection.

Playwright itself is not exercised — the fetcher's Playwright path is
monkeypatched via a stub context/page object. Wayback HTTP calls are
mocked with respx (already a dev dependency).
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import pytest
import respx

from src.rss.paywall_fetcher import PaywallFetcher


# ─── Playwright stub helpers ────────────────────────────────────


@dataclass
class _StubPage:
    html: str
    final_url: str

    def goto(self, url, wait_until=None, timeout=None):
        # Real Playwright updates .url to the post-redirect location; we
        # keep final_url as the canonical post-navigation URL.
        return None

    def content(self):
        return self.html

    def close(self):
        return None

    @property
    def url(self):
        return self.final_url


class _StubContext:
    def __init__(self, page: _StubPage):
        self._page = page

    def new_page(self):
        return self._page


def _install_playwright_stub(fetcher: PaywallFetcher, page: _StubPage):
    """Inject a stub context so _ensure_browser() is a no-op."""
    fetcher._context = _StubContext(page)
    fetcher._playwright = object()  # non-None sentinel


# ─── Fixtures ───────────────────────────────────────────────────


@pytest.fixture
def fetcher(tmp_path):
    return PaywallFetcher(
        paywall_domains=["bloomberg.com", "reuters.com"],
        browser_data_dir=tmp_path / "profile",
        timeout_ms=1_000,
        max_content_chars=15_000,
        wayback_fallback=True,
        wayback_timeout_seconds=5,
        min_content_chars=200,
    )


# ─── Domain matching ────────────────────────────────────────────


def test_needs_paywall_fetch_matches_subdomain(fetcher):
    assert fetcher.needs_paywall_fetch("https://www.bloomberg.com/news/x")
    assert fetcher.needs_paywall_fetch("https://bloomberg.com/opinion/x")
    assert not fetcher.needs_paywall_fetch("https://example.com/x")


# ─── Happy path ─────────────────────────────────────────────────


def test_playwright_success_no_fallback(fetcher):
    html = "<html><body><article>" + ("Real article body. " * 100) + "</article></body></html>"
    _install_playwright_stub(
        fetcher, _StubPage(html=html, final_url="https://www.bloomberg.com/news/x"),
    )

    result = fetcher.fetch_article(
        "https://www.bloomberg.com/news/x", rss_description="rss-snippet",
    )
    assert result.fetched is True
    assert "Real article body" in result.content
    assert fetcher.stats.playwright_ok == 1
    assert fetcher.stats.session_expiry_suspected == 0
    assert fetcher.stats.wayback_ok == 0


# ─── Session-expiry detection ───────────────────────────────────


def test_session_expiry_detected_via_login_url(fetcher):
    # Playwright returned content but redirected to /signin
    html = "<html><body><p>Please log in.</p></body></html>"
    _install_playwright_stub(
        fetcher,
        _StubPage(html=html, final_url="https://www.bloomberg.com/signin?redirect=/article"),
    )

    with respx.mock:
        # No Wayback snapshot -> should fall through to RSS
        respx.get("https://archive.org/wayback/available").mock(
            return_value=httpx.Response(200, json={"archived_snapshots": {}}),
        )
        result = fetcher.fetch_article(
            "https://www.bloomberg.com/opinion/x", rss_description="rss-snippet",
        )

    assert result.fetched is False
    assert result.content == "rss-snippet"
    assert fetcher.stats.session_expiry_suspected == 1
    assert "bloomberg.com" in fetcher.stats.suspected_domains
    assert fetcher.stats.rss_fallback == 1


def test_session_expiry_detected_via_login_keywords(fetcher):
    # Short content with paywall phrasing -> login wall even if URL looks normal
    html = "<html><body><p>Subscribe to continue reading.</p></body></html>"
    _install_playwright_stub(
        fetcher,
        _StubPage(html=html, final_url="https://www.bloomberg.com/news/x"),
    )

    with respx.mock:
        respx.get("https://archive.org/wayback/available").mock(
            return_value=httpx.Response(200, json={"archived_snapshots": {}}),
        )
        result = fetcher.fetch_article(
            "https://www.bloomberg.com/news/x", rss_description="rss-snippet",
        )

    assert fetcher.stats.session_expiry_suspected == 1
    assert result.content == "rss-snippet"


# ─── Wayback fallback ───────────────────────────────────────────


def test_wayback_fallback_after_playwright_failure(fetcher):
    # Stub: no context installed -> _ensure_browser() will import playwright
    # and fail in test env. We simulate that by installing a page that raises.
    class _RaisingPage(_StubPage):
        def goto(self, url, wait_until=None, timeout=None):
            raise RuntimeError("nav failed")

    _install_playwright_stub(
        fetcher, _RaisingPage(html="", final_url="https://www.bloomberg.com/x"),
    )

    snapshot_url = "https://web.archive.org/web/20260101/https://www.bloomberg.com/x"
    snapshot_html = (
        "<html><body><article>"
        + ("Wayback-served body content. " * 50)
        + "</article></body></html>"
    )

    with respx.mock:
        respx.get("https://archive.org/wayback/available").mock(
            return_value=httpx.Response(
                200,
                json={
                    "archived_snapshots": {
                        "closest": {
                            "available": True,
                            "status": "200",
                            "url": snapshot_url,
                        }
                    }
                },
            ),
        )
        respx.get(snapshot_url).mock(
            return_value=httpx.Response(200, text=snapshot_html),
        )

        result = fetcher.fetch_article(
            "https://www.bloomberg.com/x", rss_description="rss-snippet",
        )

    assert result.fetched is True
    assert "Wayback-served body content" in result.content
    assert fetcher.stats.wayback_ok == 1
    assert fetcher.stats.playwright_fail == 1


def test_wayback_disabled_drops_to_rss(tmp_path):
    fetcher = PaywallFetcher(
        paywall_domains=["bloomberg.com"],
        browser_data_dir=tmp_path / "profile",
        wayback_fallback=False,
        min_content_chars=200,
    )

    class _RaisingPage(_StubPage):
        def goto(self, url, wait_until=None, timeout=None):
            raise RuntimeError("nav failed")

    _install_playwright_stub(
        fetcher, _RaisingPage(html="", final_url="https://www.bloomberg.com/x"),
    )

    result = fetcher.fetch_article(
        "https://www.bloomberg.com/x", rss_description="rss-snippet",
    )
    assert result.fetched is False
    assert result.content == "rss-snippet"
    assert fetcher.stats.wayback_ok == 0
    assert fetcher.stats.wayback_fail == 0  # never attempted


def test_wayback_no_snapshot_available(fetcher):
    class _RaisingPage(_StubPage):
        def goto(self, url, wait_until=None, timeout=None):
            raise RuntimeError("nav failed")

    _install_playwright_stub(
        fetcher, _RaisingPage(html="", final_url="https://www.bloomberg.com/x"),
    )

    with respx.mock:
        respx.get("https://archive.org/wayback/available").mock(
            return_value=httpx.Response(
                200,
                json={"archived_snapshots": {"closest": {"available": False}}},
            ),
        )
        result = fetcher.fetch_article(
            "https://www.bloomberg.com/x", rss_description="rss-snippet",
        )

    assert result.fetched is False
    assert fetcher.stats.wayback_fail == 1
    assert fetcher.stats.rss_fallback == 1


# ─── Stats round-trip ───────────────────────────────────────────


def test_stats_as_dict_shape(fetcher):
    d = fetcher.stats.as_dict()
    assert set(d.keys()) == {
        "attempts", "playwright_ok", "playwright_fail",
        "session_expiry_suspected", "wayback_ok", "wayback_fail",
        "rss_fallback", "suspected_domains",
    }
