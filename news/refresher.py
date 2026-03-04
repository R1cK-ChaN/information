"""Continuous news feed refresher.

Pipeline on startup and every REFRESH_INTERVAL_SECONDS thereafter:

  1. stream.refresh()              → information/output/<sha>.json + catalog.db
  2. export_information_layer.py   → information/6_information_layer/news/<sha[:12]>.md
  3. POST /admin/collections/sync  → RAG Milvus incremental index

Export and RAG sync are only triggered when new items were stored.
RAG sync failure is non-fatal — logged as a warning and retried next cycle.

Environment variables
---------------------
REFRESH_INTERVAL_SECONDS  How often to poll (default: 900 = 15 min)
RAG_SERVICE_URL           Full URL of the RAG service (default: http://localhost:8000)
RAG_API_KEY               Optional X-API-Key header for the RAG service
CATALOG_PATH              Override path to catalog.db
INFO_LAYER_PATH           Override path to 6_information_layer/ output directory
EXPORT_SCRIPT             Override path to export_information_layer.py
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

from src.news_stream import NewsStream

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

# ── logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("refresher")


# ── helpers ───────────────────────────────────────────────────────────────────

def export_information_layer() -> bool:
    """Run export_information_layer.py to write .md files into 6_information_layer/."""
    if not EXPORT_SCRIPT.exists():
        log.warning("Export script not found at %s — skipping", EXPORT_SCRIPT)
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
    """POST /admin/collections/sync to trigger incremental Milvus indexing."""
    headers: dict[str, str] = {}
    if RAG_API_KEY:
        headers["X-API-Key"] = RAG_API_KEY

    try:
        resp = httpx.post(
            f"{RAG_URL}/admin/collections/sync",
            headers=headers,
            timeout=120.0,
        )
        resp.raise_for_status()
        log.info("RAG sync triggered: %s", resp.json())
    except Exception as exc:
        log.warning("RAG sync trigger failed (will retry next cycle): %s", exc)


def run_refresh(stream: NewsStream, is_bootstrap: bool = False) -> int:
    """Run one refresh or bootstrap cycle. Returns number of items stored."""
    label = "bootstrap" if is_bootstrap else "refresh"
    log.info("Starting %s...", label)

    result = stream.bootstrap() if is_bootstrap else stream.refresh()

    stored     = result.get("stored", 0)
    fetched    = result.get("fetched", 0)
    duplicates = result.get("duplicates", 0)
    errors     = result.get("errors", [])

    log.info(
        "%s done — fetched=%d  stored=%d  duplicates=%d  errors=%d",
        label, fetched, stored, duplicates, len(errors),
    )
    for err in errors[:5]:
        log.debug("  error: %s", err)
    if len(errors) > 5:
        log.debug("  ... and %d more errors", len(errors) - 5)

    return stored


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    log.info("=" * 60)
    log.info("News refresher starting")
    log.info("  interval:   %ds (%.0f min)", INTERVAL, INTERVAL / 60)
    log.info("  catalog:    %s", CATALOG_PATH)
    log.info("  info_layer: %s", INFO_LAYER_PATH)
    log.info("  export:     %s", EXPORT_SCRIPT)
    log.info("  rag_url:    %s", RAG_URL)
    log.info("=" * 60)

    stream = NewsStream()

    # ── bootstrap: full first-run across all feeds ────────────────────────────
    stored = run_refresh(stream, is_bootstrap=True)
    if stored > 0:
        if export_information_layer():
            trigger_rag_sync()

    # ── continuous loop ───────────────────────────────────────────────────────
    while True:
        log.info("Sleeping %ds until next refresh...", INTERVAL)
        time.sleep(INTERVAL)

        stored = run_refresh(stream)
        if stored > 0:
            if export_information_layer():
                trigger_rag_sync()
        else:
            log.info("No new items — skipping export + RAG sync")


if __name__ == "__main__":
    main()
