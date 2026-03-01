"""Pipeline: fetch → convert → extract → save.

Integrates with doc_parser for LLM entity extraction and JSON storage.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from doc_parser.steps.step3_extract import parse_date_to_epoch, run_extraction
from doc_parser.storage import has_result, save_result

from gov_report.config import Settings
from gov_report.converter import html_to_markdown
from gov_report.hasher import content_sha
from gov_report.models import FetchResult
from gov_report.sync_store import SyncStore

logger = logging.getLogger(__name__)


async def process_report(
    settings: Settings,
    fetch_result: FetchResult,
    *,
    force: bool = False,
) -> dict | None:
    """Process a single fetched report through the full pipeline.

    1. Compute sha256(url + publish_date)
    2. Dedup check
    3. HTML → markdown → run_extraction → save
       OR PDF → delegate to doc_parser.pipeline.process_file
    4. Record in sync_store

    Returns the result dict, or None if skipped.
    """
    sha = content_sha(fetch_result.url, fetch_result.publish_date)
    store = SyncStore(settings.sync_db_path)

    try:
        # Dedup check
        if not force and has_result(settings.extraction_path, sha):
            logger.info("Skipping %s -- result exists", fetch_result.source_id)
            return None

        if fetch_result.content_type == "pdf":
            result = await _process_pdf(settings, sha, fetch_result)
        else:
            result = await _process_html(settings, sha, fetch_result)

        if result is None:
            return None

        # Override known fields with crawler metadata
        result["institution"] = fetch_result.institution
        result["country"] = fetch_result.country
        result["language"] = fetch_result.language

        # Save
        path = save_result(settings.extraction_path, result)
        logger.info("Saved result to %s", path)

        # Record success
        store.record_fetch(
            sha=sha,
            source_id=fetch_result.source_id,
            url=fetch_result.url,
            publish_date=fetch_result.publish_date,
        )
        return result

    except Exception as exc:
        logger.error("Failed to process %s: %s", fetch_result.url, exc)
        store.record_fetch(
            sha=sha,
            source_id=fetch_result.source_id,
            url=fetch_result.url,
            publish_date=fetch_result.publish_date,
            status="error",
            error_message=str(exc),
        )
        raise
    finally:
        store.close()


async def _process_html(
    settings: Settings, sha: str, fr: FetchResult
) -> dict:
    """Convert HTML to markdown, run LLM extraction, assemble result."""
    markdown = html_to_markdown(fr.content_html)

    # Build doc_parser Settings for LLM extraction
    dp_settings = settings.to_doc_parser_settings()

    # Run extraction (same prompt and fields as doc_parser)
    ext_result = await run_extraction(
        dp_settings,
        file_path=Path(fr.url),  # placeholder path for the provider
        markdown=markdown,
    )

    fields = ext_result.fields
    return {
        "sha256": sha,
        "file_name": fr.title or fr.source_id,
        "source": f"gov_report:{fr.source_id}",
        "local_path": fr.url,
        "mime_type": "text/html",
        "file_size_bytes": len(fr.content_html.encode("utf-8")),
        "processed_at": int(time.time()),
        # Entity fields — LLM-extracted then overridden
        "title": fields.get("title") or fr.title,
        "institution": fr.institution,
        "authors": fields.get("authors"),
        "publish_date": fields.get("publish_date") or fr.publish_date,
        "data_period": fields.get("data_period"),
        "country": fr.country,
        "market": fields.get("market"),
        "asset_class": fields.get("asset_class"),
        "sector": fields.get("sector"),
        "document_type": fields.get("document_type"),
        "event_type": fields.get("event_type"),
        "subject": fields.get("subject"),
        "subject_id": fields.get("subject_id"),
        "language": fr.language,
        "contains_commentary": fields.get("contains_commentary"),
        "impact_level": fields.get("impact_level"),
        "confidence": fields.get("confidence"),
        # Content
        "markdown": markdown,
        # Parse info (HTML — no OCR parse)
        "parse_info": {
            "page_count": 1,
            "has_chart": False,
            "has_table": bool("<table" in fr.content_html.lower()),
            "chart_count": 0,
            "table_count": fr.content_html.lower().count("<table"),
            "duration_ms": 0,
            "parse_mode": "html_crawl",
        },
        # Extraction info
        "extraction_info": {
            "provider": "llm",
            "llm_model": settings.llm_model,
            "duration_ms": ext_result.duration_ms,
        },
    }


async def _process_pdf(
    settings: Settings, sha: str, fr: FetchResult
) -> dict | None:
    """Delegate PDF processing to doc_parser.pipeline.process_file."""
    from doc_parser.pipeline import process_file

    if not fr.pdf_bytes:
        raise ValueError(f"PDF fetch result has no pdf_bytes: {fr.url}")

    # Save PDF to download dir
    pdf_path = settings.download_path / f"{sha}.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(fr.pdf_bytes)

    dp_settings = settings.to_doc_parser_settings()
    # Override extraction_path so doc_parser saves to our data dir
    dp_settings = Settings(
        **{
            **dp_settings.model_dump(),
            "data_dir": settings.data_dir,
        }
    )

    result = await process_file(
        dp_settings,
        sha,
        pdf_path,
        source=f"gov_report:{fr.source_id}",
        file_name=fr.title or f"{fr.source_id}.pdf",
        force=True,
    )
    return result


# -- High-level entry points for CLI ----------------------------------------


async def process_source(
    settings: Settings, source_id: str, *, force: bool = False
) -> list[dict]:
    """Fetch and process all latest reports from a single source."""
    from gov_report.fetchers import get_fetcher

    fetcher = get_fetcher(source_id, settings)
    fetch_results = await fetcher.fetch_latest()
    results = []
    for fr in fetch_results:
        result = await process_report(settings, fr, force=force)
        if result is not None:
            results.append(result)
    return results


async def process_all_sources(
    settings: Settings, *, country: str = "all", force: bool = False
) -> list[dict]:
    """Fetch and process all latest reports from all configured sources."""
    from gov_report.registry import SOURCES

    results = []
    for source_id, cfg in SOURCES.items():
        if country != "all" and cfg.country.lower() != country:
            continue
        try:
            batch = await process_source(settings, source_id, force=force)
            results.extend(batch)
        except Exception as exc:
            logger.error("Source %s failed: %s", source_id, exc)
    return results


async def process_rss_items(
    settings: Settings, items: list, *, force: bool = False
) -> list[dict]:
    """Process a list of RSS items through the pipeline."""
    from gov_report.fetchers import get_fetcher

    results = []
    for item in items:
        try:
            fetcher = get_fetcher(item.source_id, settings)
            fr = await fetcher.fetch_by_url(item.url)
            result = await process_report(settings, fr, force=force)
            if result is not None:
                results.append(result)
        except Exception as exc:
            logger.error("RSS item %s failed: %s", item.url, exc)
    return results
