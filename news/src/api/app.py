"""FastAPI application for Telegram news SSE streaming and REST queries."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse

from .broadcast import BroadcastHub
from .filters import matches_filter

logger = logging.getLogger(__name__)


def create_app(hub: BroadcastHub, catalog) -> FastAPI:
    """Factory: create a FastAPI app wired to *hub* and *catalog*."""

    app = FastAPI(title="News SSE API", version="0.1.0")

    # ── GET / (frontend) ────────────────────────────────────────────────
    _FRONTEND = Path(__file__).resolve().parent.parent.parent.parent / "widgets" / "news_stream.html"

    @app.get("/", response_class=HTMLResponse)
    async def index():
        if _FRONTEND.exists():
            return HTMLResponse(_FRONTEND.read_text(encoding="utf-8"))
        raise HTTPException(status_code=404, detail="Frontend not found")

    # ── GET /health ───────────────────────────────────────────────────────
    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "subscribers": hub.subscriber_count,
            "catalog_items": catalog.count(source="news"),
        }

    # ── GET /stream (SSE) ─────────────────────────────────────────────────
    @app.get("/stream")
    async def stream(
        impact_level: str | None = Query(None),
        market: str | None = Query(None),
        asset_class: str | None = Query(None),
        sector: str | None = Query(None),
        institution: str | None = Query(None),
        event_type: str | None = Query(None),
    ):
        filters = dict(
            impact_level=impact_level,
            market=market,
            asset_class=asset_class,
            sector=sector,
            institution=institution,
            event_type=event_type,
        )

        async def event_generator() -> AsyncGenerator[str, None]:
            sub_id, queue = hub.subscribe()
            try:
                while True:
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=30.0)
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
                        continue

                    # Shutdown sentinel
                    if item is None:
                        return

                    if matches_filter(item, **filters):
                        yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            finally:
                hub.unsubscribe(sub_id)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # ── GET /items (REST historical query) ────────────────────────────────
    @app.get("/items")
    async def items(
        impact_level: str | None = Query(None),
        market: str | None = Query(None),
        asset_class: str | None = Query(None),
        sector: str | None = Query(None),
        institution: str | None = Query(None),
        event_type: str | None = Query(None),
        limit: int = Query(50, ge=1, le=500),
    ):
        filters = dict(
            impact_level=impact_level,
            market=market,
            asset_class=asset_class,
            sector=sector,
            institution=institution,
            event_type=event_type,
        )

        # Pull a larger batch from catalog and post-filter
        # Catalog supports source + impact_level natively
        rows = catalog.get_latest(
            limit * 5,
            source="news",
            impact_level=impact_level,
        )

        # Filter to Telegram-only items and apply remaining filters
        result = []
        for row in rows:
            inst = row.get("institution") or ""
            if not inst.startswith("TG "):
                continue
            # Skip impact_level in post-filter (already used in SQL)
            post_filters = {k: v for k, v in filters.items() if k != "impact_level"}
            if not matches_filter(row, **post_filters):
                continue

            # Enrich with markdown from JSON file
            json_path = row.get("json_path")
            if json_path:
                p = Path(str(json_path))
                if p.exists():
                    try:
                        data = json.loads(p.read_text(encoding="utf-8"))
                        row["markdown"] = data.get("markdown", "")
                    except Exception:
                        pass

            result.append(row)
            if len(result) >= limit:
                break

        return JSONResponse(result)

    # ── GET /items/{sha256} (single item detail) ──────────────────────────
    @app.get("/items/{sha256}")
    async def item_detail(sha256: str):
        rows = catalog.get_latest(1, source="news")
        # Search catalog for this specific sha
        # Use a direct approach: check if item exists then read its JSON
        if not catalog.has(sha256):
            raise HTTPException(status_code=404, detail="Item not found")

        # Find the json_path from catalog
        import sqlite3
        conn = sqlite3.connect(str(catalog.db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT * FROM items WHERE sha256 = ?", (sha256,)
        )
        row = cur.fetchone()
        conn.close()

        if row is None:
            raise HTTPException(status_code=404, detail="Item not found")

        row_dict = dict(row)
        json_path = row_dict.get("json_path")
        if json_path:
            p = Path(str(json_path))
            if p.exists():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    return JSONResponse(data)
                except Exception:
                    pass

        return JSONResponse(row_dict)

    return app
