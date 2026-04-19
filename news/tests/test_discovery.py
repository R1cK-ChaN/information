"""Discovery module tests (search + fetch + reference extraction)."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

# src/__init__.py imports widgets.catalog (via news_stream); make sure the
# repo root is on sys.path before that cascade runs.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.discovery import extract_urls, fetch_url, search
from src.discovery.fetch import FetchResult
from src.discovery.search import SearchResult


class TestExtractUrls:
    def test_extracts_unique_urls(self):
        md = "See [Reuters](https://reuters.com/a) and also https://ft.com/x."
        assert extract_urls(md) == ["https://reuters.com/a", "https://ft.com/x"]

    def test_ignores_duplicates(self):
        md = "https://a.com http://b.com https://a.com"
        urls = extract_urls(md)
        assert urls == ["https://a.com", "http://b.com"]

    def test_respects_limit(self):
        md = "\n".join(f"https://s{i}.com" for i in range(10))
        assert len(extract_urls(md, limit=3)) == 3

    def test_empty_input(self):
        assert extract_urls("") == []
        assert extract_urls(None) == []

    def test_does_not_match_non_http(self):
        md = "mailto://me@x.com ftp://foo.bar https://x.com"
        assert extract_urls(md) == ["https://x.com"]


class TestSearch:
    def test_returns_empty_when_api_key_unset(self, monkeypatch):
        monkeypatch.delenv("BRAVE_API_KEY", raising=False)
        assert search("anything") == []

    def test_returns_empty_on_blank_query(self, monkeypatch):
        monkeypatch.setenv("BRAVE_API_KEY", "fake")
        assert search("   ") == []

    def test_parses_brave_payload(self, monkeypatch):
        monkeypatch.setenv("BRAVE_API_KEY", "fake")

        def fake_get(url, params=None, headers=None, timeout=None):
            return httpx.Response(
                200,
                json={
                    "web": {
                        "results": [
                            {"title": "Reuters", "url": "https://reuters.com/a",
                             "description": "a summary"},
                            {"title": "FT", "url": "https://ft.com/b",
                             "description": "b summary"},
                        ]
                    }
                },
                request=httpx.Request("GET", url),
            )

        monkeypatch.setattr(httpx, "get", fake_get)
        results = search("cpi release", limit=2)
        assert len(results) == 2
        assert isinstance(results[0], SearchResult)
        assert results[0].url == "https://reuters.com/a"

    def test_returns_empty_on_http_error(self, monkeypatch):
        monkeypatch.setenv("BRAVE_API_KEY", "fake")

        def raises(*a, **kw):
            raise httpx.ConnectError("boom")

        monkeypatch.setattr(httpx, "get", raises)
        assert search("anything") == []


class TestFetchUrl:
    def test_returns_body_on_200(self, monkeypatch):

        def fake_get(url, timeout=None, follow_redirects=None, headers=None):
            return httpx.Response(200, text="hello body",
                                  request=httpx.Request("GET", url))

        monkeypatch.setattr(httpx, "get", fake_get)
        r = fetch_url("https://example.com/a")
        assert isinstance(r, FetchResult)
        assert r.status == 200
        assert r.text == "hello body"
        assert r.via_paywall is False

    def test_returns_error_on_4xx_without_fallback(self, monkeypatch):

        def fake_get(url, timeout=None, follow_redirects=None, headers=None):
            return httpx.Response(403, request=httpx.Request("GET", url))

        monkeypatch.setattr(httpx, "get", fake_get)
        r = fetch_url("https://example.com/a")
        assert r.status == 403
        assert r.error == "HTTP 403"
        assert r.via_paywall is False

    def test_uses_paywall_fallback_on_4xx(self, monkeypatch):

        def fake_get(url, timeout=None, follow_redirects=None, headers=None):
            return httpx.Response(401, request=httpx.Request("GET", url))

        monkeypatch.setattr(httpx, "get", fake_get)

        class FakePaywall:
            def fetch(self, url):
                class Art:
                    content = "rescued text"
                return Art()

        r = fetch_url("https://example.com/a", paywall_fetcher=FakePaywall())
        assert r.status == 401
        assert r.text == "rescued text"
        assert r.via_paywall is True

    def test_network_error_returns_zero_status(self, monkeypatch):

        def raises(*a, **kw):
            raise httpx.ConnectTimeout("timeout")

        monkeypatch.setattr(httpx, "get", raises)
        r = fetch_url("https://example.com/a")
        assert r.status == 0
        assert "timeout" in (r.error or "").lower()


class TestNewsletterIntegration:
    """The newsletter parser calls extract_urls automatically so sections
    surface referenced URLs for ingestion code to chase."""

    def test_section_populates_references(self):
        from src.newsletter.parsers import generic_parser
        html = (
            "<h2>Macro</h2>"
            "<p>See the Reuters piece at https://reuters.com/cpi and the FT"
            " at <a href='https://ft.com/x'>this link</a>.</p>"
        )
        sections = generic_parser(html, "")
        assert sections
        refs = sections[0].references
        assert "https://reuters.com/cpi" in refs
        assert "https://ft.com/x" in refs
