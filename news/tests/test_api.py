"""Tests for the SSE API endpoints."""

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.api.broadcast import BroadcastHub
from src.api.app import create_app


@pytest.fixture
def mock_catalog(tmp_path):
    """Minimal mock catalog that supports the methods used by the API."""
    import sqlite3

    db_path = tmp_path / "catalog.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS items (
            sha256 TEXT PRIMARY KEY, json_path TEXT, source TEXT,
            title TEXT, institution TEXT, publish_date TEXT,
            data_period TEXT, country TEXT, market TEXT,
            asset_class TEXT, sector TEXT, document_type TEXT,
            event_type TEXT, subject TEXT, subject_id TEXT,
            language TEXT, contains_commentary INTEGER,
            impact_level TEXT, confidence REAL, processed_at INTEGER
        );
    """)
    conn.close()

    catalog = MagicMock()
    catalog.db_path = str(db_path)
    catalog.count.return_value = 0
    catalog.has.return_value = False
    catalog.get_latest.return_value = []
    return catalog


@pytest.fixture
def hub():
    loop = asyncio.new_event_loop()
    h = BroadcastHub(loop=loop)
    yield h
    loop.close()


@pytest.fixture
def client(hub, mock_catalog):
    app = create_app(hub, mock_catalog)
    return TestClient(app)


def test_health(client, mock_catalog):
    mock_catalog.count.return_value = 42
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["catalog_items"] == 42


def test_items_empty(client):
    resp = client.get("/items")
    assert resp.status_code == 200
    assert resp.json() == []


def test_items_filters_telegram_only(client, mock_catalog):
    mock_catalog.get_latest.return_value = [
        {"sha256": "a1", "institution": "TG Bloomberg", "impact_level": "high",
         "market": "Global Markets", "title": "Test"},
        {"sha256": "a2", "institution": "Reuters RSS", "impact_level": "high",
         "market": "Global Markets", "title": "Non-TG"},
    ]
    resp = client.get("/items?impact_level=high")
    data = resp.json()
    assert len(data) == 1
    assert data[0]["institution"] == "TG Bloomberg"


def test_items_with_market_filter(client, mock_catalog):
    mock_catalog.get_latest.return_value = [
        {"sha256": "a1", "institution": "TG Bloomberg", "impact_level": "high",
         "market": "Global Markets", "title": "Match"},
        {"sha256": "a2", "institution": "TG Reuters", "impact_level": "high",
         "market": "Crypto", "title": "No match"},
    ]
    resp = client.get("/items?market=Global")
    data = resp.json()
    assert len(data) == 1
    assert data[0]["sha256"] == "a1"


def test_item_detail_not_found(client, mock_catalog):
    resp = client.get("/items/deadbeef")
    assert resp.status_code == 404


def test_item_detail_with_json(client, mock_catalog, tmp_path):
    # Write a JSON extraction file
    json_file = tmp_path / "test.json"
    payload = {"sha256": "abc123", "markdown": "# Hello", "title": "Test"}
    json_file.write_text(json.dumps(payload), encoding="utf-8")

    mock_catalog.has.return_value = True

    # Insert row into the actual sqlite db
    import sqlite3
    conn = sqlite3.connect(mock_catalog.db_path)
    conn.execute(
        "INSERT INTO items (sha256, json_path, source, title, institution) "
        "VALUES (?, ?, ?, ?, ?)",
        ("abc123", str(json_file), "news", "Test", "TG Bloomberg"),
    )
    conn.commit()
    conn.close()

    resp = client.get("/items/abc123")
    assert resp.status_code == 200
    data = resp.json()
    assert data["markdown"] == "# Hello"


@pytest.mark.asyncio
async def test_stream_receives_published_item():
    """Verify the SSE event generator yields published items."""
    loop = asyncio.get_running_loop()
    hub = BroadcastHub(loop=loop)
    mock_cat = MagicMock(count=MagicMock(return_value=0))
    app = create_app(hub, mock_cat)

    # Use httpx.AsyncClient with ASGI transport for true async SSE
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        item = {"title": "Breaking", "impact_level": "critical", "institution": "TG Test"}

        async def publish_after_delay():
            await asyncio.sleep(0.2)
            hub.publish(item)
            await asyncio.sleep(0.1)
            await hub.shutdown()  # sends sentinel so stream exits

        publish_task = asyncio.create_task(publish_after_delay())

        received = []
        async with ac.stream("GET", "/stream") as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    received.append(json.loads(line[6:]))
                    break

        await publish_task
        assert len(received) == 1
        assert received[0]["title"] == "Breaking"
