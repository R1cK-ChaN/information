"""Continuous news feed refresher with optional Telegram real-time monitoring.

Pipeline on startup and every REFRESH_INTERVAL_SECONDS thereafter:

  1. stream.refresh()              -> information/output/<sha>.json + catalog.db
  2. export_information_layer.py   -> information/6_information_layer/news/<sha[:12]>.md
  3. POST /admin/collections/sync  -> RAG Milvus incremental index

When TELEGRAM_REALTIME_ENABLED=true, a Telethon listener pushes incoming
messages into an asyncio.Queue.  A consumer task batches them (every 30s or
10 items) and processes them through the same pipeline.  The polling loop
skips Telegram feeds while the real-time connection is up.

Export and RAG sync are only triggered when new items were stored.
RAG sync failure is non-fatal -- logged as a warning and retried next cycle.

Environment variables
---------------------
REFRESH_INTERVAL_SECONDS    How often to poll (default: 900 = 15 min)
RAG_SERVICE_URL             Full URL of the RAG service (default: http://localhost:8000)
RAG_API_KEY                 Optional X-API-Key header for the RAG service
CATALOG_PATH                Override path to catalog.db
INFO_LAYER_PATH             Override path to 6_information_layer/ output directory
EXPORT_SCRIPT               Override path to export_information_layer.py
TELEGRAM_REALTIME_ENABLED   Enable Telethon real-time listener (default: false)
TELEGRAM_API_ID             Telegram API application ID
TELEGRAM_API_HASH           Telegram API application hash
TELEGRAM_BATCH_INTERVAL     Seconds between real-time batch flushes (default: 30)
TELEGRAM_BATCH_SIZE         Max items per real-time batch (default: 10)
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx

from src.news_stream import NewsStream
from src.registry import FEEDS

# ── paths ─────────────────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent          # information/news/
_INFO = _HERE.parent                             # information/

_CATALOG_DEFAULT     = _INFO / "output" / "catalog.db"
_INFO_LAYER_DEFAULT  = _INFO / "6_information_layer"
_EXPORT_DEFAULT      = _INFO.parent / "rag-service" / "scripts" / "export_information_layer.py"

# ── config ────────────────────────────────────────────────────────────────────
INTERVAL        = int(os.getenv("REFRESH_INTERVAL_SECONDS", "900"))
RAG_URL         = os.getenv("RAG_SERVICE_URL", "http://localhost:8000").rstrip("/")
RAG_API_KEY     = os.getenv("RAG_API_KEY", "")
CATALOG_PATH    = Path(os.getenv("CATALOG_PATH",    str(_CATALOG_DEFAULT)))
INFO_LAYER_PATH = Path(os.getenv("INFO_LAYER_PATH", str(_INFO_LAYER_DEFAULT)))
EXPORT_SCRIPT   = Path(os.getenv("EXPORT_SCRIPT",   str(_EXPORT_DEFAULT)))

# Telegram real-time config
TG_RT_ENABLED    = os.getenv("TELEGRAM_REALTIME_ENABLED", "false").lower() in ("true", "1", "yes")
TG_API_ID        = os.getenv("TELEGRAM_API_ID", "")
TG_API_HASH      = os.getenv("TELEGRAM_API_HASH", "")
TG_BATCH_INTERVAL = int(os.getenv("TELEGRAM_BATCH_INTERVAL", "30"))
TG_BATCH_SIZE     = int(os.getenv("TELEGRAM_BATCH_SIZE", "10"))

# ── logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("refresher")

_TG_URL_RE = re.compile(r"https?://t\.me/s/(\w+)")


# ── helpers ───────────────────────────────────────────────────────────────────

def export_information_layer() -> bool:
    """Run export_information_layer.py to write .md files into 6_information_layer/."""
    if not EXPORT_SCRIPT.exists():
        log.warning("Export script not found at %s -- skipping", EXPORT_SCRIPT)
        return False

    cmd = [
        sys.executable, str(EXPORT_SCRIPT),
        "--catalog",     str(CATALOG_PATH),
        "--output-dir",  str(INFO_LAYER_PATH),
        "--max-age-days", "180",
    ]
    log.info("Running export: %s", " ".join(str(c) for c in cmd))

    proc = subprocess.run(cmd, capture_output=True, text=True)

    if proc.stdout.strip():
        log.info("Export output: %s", proc.stdout.strip())
    if proc.returncode != 0:
        log.error("Export failed (rc=%d): %s", proc.returncode, proc.stderr.strip())
        return False
    return True


def trigger_rag_sync() -> None:
    """POST /admin/collections/sync and self-heal missing-manifest bootstrap cases."""
    headers: dict[str, str] = {}
    if RAG_API_KEY:
        headers["X-API-Key"] = RAG_API_KEY

    try:
        resp = httpx.post(
            f"{RAG_URL}/admin/collections/sync",
            headers=headers,
            json={"auto_full_reindex_on_version_mismatch": True},
            timeout=120.0,
        )

        if resp.status_code == 409:
            try:
                data = resp.json()
            except Exception:
                data = {}

            if (
                data.get("error_code") == "KB_SYNC_REQUIRES_FULL_REINDEX"
                and data.get("reason") == "missing_manifest"
            ):
                log.info(
                    "RAG sync requires full bootstrap reindex (missing manifest); triggering force_full_reindex"
                )
                full_resp = httpx.post(
                    f"{RAG_URL}/admin/collections/sync",
                    headers=headers,
                    json={"force_full_reindex": True},
                    timeout=600.0,
                )
                full_resp.raise_for_status()
                log.info("RAG full reindex triggered: %s", full_resp.json())
                return

        resp.raise_for_status()
        log.info("RAG sync triggered: %s", resp.json())
    except Exception as exc:
        log.warning("RAG sync trigger failed (will retry next cycle): %s", exc)


def run_refresh(
    stream: NewsStream,
    is_bootstrap: bool = False,
    skip_telegram: bool = False,
) -> int:
    """Run one refresh or bootstrap cycle. Returns number of items stored."""
    label = "bootstrap" if is_bootstrap else ("refresh (skip_tg)" if skip_telegram else "refresh")
    log.info("Starting %s...", label)

    if is_bootstrap:
        result = stream.bootstrap()
    else:
        result = stream.refresh(skip_telegram=skip_telegram)

    stored     = result.get("stored", 0)
    fetched    = result.get("fetched", 0)
    duplicates = result.get("duplicates", 0)
    errors     = result.get("errors", [])

    log.info(
        "%s done -- fetched=%d  stored=%d  duplicates=%d  errors=%d",
        label, fetched, stored, duplicates, len(errors),
    )
    for err in errors[:5]:
        log.debug("  error: %s", err)
    if len(errors) > 5:
        log.debug("  ... and %d more errors", len(errors) - 5)

    return stored


def _export_and_sync() -> None:
    """Run export + RAG sync pipeline."""
    if export_information_layer():
        trigger_rag_sync()


def _build_channel_map() -> dict[str, dict]:
    """Build channel_map from registry FEEDS (filter t.me/s/ URLs)."""
    channel_map: dict[str, dict] = {}
    for feed in FEEDS:
        m = _TG_URL_RE.match(feed.url)
        if m:
            username = m.group(1).lower()
            channel_map[username] = {
                "feed_name": feed.name,
                "feed_category": feed.category,
            }
    return channel_map


# ── async main ────────────────────────────────────────────────────────────────

async def async_main() -> None:
    log.info("=" * 60)
    log.info("News refresher starting")
    log.info("  interval:   %ds (%.0f min)", INTERVAL, INTERVAL / 60)
    log.info("  catalog:    %s", CATALOG_PATH)
    log.info("  info_layer: %s", INFO_LAYER_PATH)
    log.info("  export:     %s", EXPORT_SCRIPT)
    log.info("  rag_url:    %s", RAG_URL)
    log.info("  telegram_rt: %s", TG_RT_ENABLED)
    log.info("=" * 60)

    stream = NewsStream()

    # Serialize all NewsStream access (SQLite is not thread-safe)
    stream_lock = asyncio.Lock()

    # ── bootstrap: full first-run across all feeds ────────────────────────────
    stored = await asyncio.to_thread(run_refresh, stream, True)
    if stored > 0:
        await asyncio.to_thread(_export_and_sync)

    # ── Telegram real-time setup ──────────────────────────────────────────────
    rt_connected = asyncio.Event()  # set when Telethon is connected
    rt_queue: asyncio.Queue[dict] = asyncio.Queue()
    tg_provider = None

    if TG_RT_ENABLED:
        tg_provider = await _start_telegram(rt_queue, rt_connected)

    # ── launch concurrent tasks ───────────────────────────────────────────────
    tasks = [
        asyncio.create_task(_polling_loop(stream, stream_lock, rt_connected)),
        asyncio.create_task(_queue_consumer(stream, stream_lock, rt_queue)),
    ]
    if tg_provider is not None:
        tasks.append(
            asyncio.create_task(_telegram_watchdog(tg_provider, rt_queue, rt_connected))
        )

    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        log.info("Shutting down...")
    finally:
        for t in tasks:
            t.cancel()
        if tg_provider is not None:
            await tg_provider.stop()
        stream.close()


async def _start_telegram(
    rt_queue: asyncio.Queue[dict],
    rt_connected: asyncio.Event,
) -> object | None:
    """Try to start the Telegram real-time provider. Returns provider or None."""
    if not TG_API_ID or not TG_API_HASH:
        log.error(
            "TELEGRAM_REALTIME_ENABLED=true but TELEGRAM_API_ID / "
            "TELEGRAM_API_HASH not set; falling back to HTTP scraping"
        )
        return None

    try:
        from src.providers.telegram_realtime import TelegramRealtimeProvider
    except ImportError:
        log.error("telethon not installed; falling back to HTTP scraping")
        return None

    channel_map = _build_channel_map()
    if not channel_map:
        log.warning("No Telegram channels found in registry")
        return None

    session_path = str(_HERE / "data" / "telegram_session" / "news_stream")

    async def on_items(items: list[dict]) -> None:
        for item in items:
            await rt_queue.put(item)

    provider = TelegramRealtimeProvider(
        api_id=int(TG_API_ID),
        api_hash=TG_API_HASH,
        channel_map=channel_map,
        on_items=on_items,
        session_path=session_path,
    )

    try:
        await provider.start()
        rt_connected.set()
        return provider
    except Exception as exc:
        log.error("Telegram real-time start failed: %s", exc)
        return None


async def _polling_loop(
    stream: NewsStream,
    lock: asyncio.Lock,
    rt_connected: asyncio.Event,
) -> None:
    """RSS + HTTP-scrape polling loop (every INTERVAL seconds)."""
    while True:
        await asyncio.sleep(INTERVAL)

        skip_tg = rt_connected.is_set()
        async with lock:
            stored = await asyncio.to_thread(run_refresh, stream, False, skip_tg)
        if stored > 0:
            await asyncio.to_thread(_export_and_sync)
        else:
            log.info("No new items -- skipping export + RAG sync")


async def _queue_consumer(
    stream: NewsStream,
    lock: asyncio.Lock,
    queue: asyncio.Queue[dict],
) -> None:
    """Drain the real-time queue; batch every BATCH_INTERVAL or BATCH_SIZE items."""
    while True:
        batch: list[dict] = []

        # Wait for at least one item
        try:
            item = await asyncio.wait_for(queue.get(), timeout=TG_BATCH_INTERVAL)
            batch.append(item)
        except asyncio.TimeoutError:
            continue

        # Drain up to BATCH_SIZE
        while len(batch) < TG_BATCH_SIZE:
            try:
                item = queue.get_nowait()
                batch.append(item)
            except asyncio.QueueEmpty:
                break

        if not batch:
            continue

        log.info("Real-time batch: processing %d items", len(batch))
        async with lock:
            stored = await asyncio.to_thread(stream.process_realtime_items, batch)
        if stored > 0:
            await asyncio.to_thread(_export_and_sync)


async def _telegram_watchdog(
    provider: object,
    queue: asyncio.Queue[dict],
    rt_connected: asyncio.Event,
) -> None:
    """Check Telethon connection every 60s; attempt reconnect if down."""
    while True:
        await asyncio.sleep(60)

        if provider.connected:  # type: ignore[union-attr]
            if not rt_connected.is_set():
                rt_connected.set()
                log.info("Telegram real-time reconnected")
        else:
            if rt_connected.is_set():
                rt_connected.clear()
                log.warning("Telegram real-time disconnected; polling will use HTTP scraping")

            # Try to reconnect
            try:
                await provider.start()  # type: ignore[union-attr]
                rt_connected.set()
                log.info("Telegram real-time reconnected")
            except Exception as exc:
                log.warning("Telegram reconnect failed: %s", exc)


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
