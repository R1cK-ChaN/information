"""Click CLI for gov-report."""

from __future__ import annotations

import asyncio
import logging
import sys

import click
from rich.console import Console
from rich.table import Table

from gov_report.config import get_settings

console = Console()


def _run(coro):
    """Run an async coroutine."""
    return asyncio.run(coro)


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
def cli(verbose: bool) -> None:
    """Government economic report crawler."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@cli.command()
@click.argument("source_id")
@click.option("--force", is_flag=True, help="Re-fetch even if already stored.")
def fetch(source_id: str, force: bool) -> None:
    """Fetch latest report(s) from a single source."""
    from gov_report.pipeline import process_source

    settings = get_settings()
    settings.ensure_dirs()
    results = _run(process_source(settings, source_id, force=force))
    if not results:
        console.print(f"[yellow]No new reports from {source_id}[/yellow]")
    else:
        for r in results:
            console.print(
                f"[green]Saved[/green] {r['title'] or r['sha256'][:12]} "
                f"→ {r['sha256'][:12]}"
            )


@cli.command("fetch-all")
@click.option(
    "--country",
    type=click.Choice(["us", "cn", "all"]),
    default="all",
    help="Filter by country.",
)
@click.option("--force", is_flag=True, help="Re-fetch even if already stored.")
def fetch_all(country: str, force: bool) -> None:
    """Fetch latest reports from all configured sources."""
    from gov_report.pipeline import process_all_sources

    settings = get_settings()
    settings.ensure_dirs()
    results = _run(process_all_sources(settings, country=country, force=force))
    console.print(f"[green]Fetched {len(results)} report(s)[/green]")


@cli.command("poll-rss")
@click.option("--feed", default=None, help="Poll a specific RSS feed key.")
@click.option("--force", is_flag=True, help="Re-fetch even if already stored.")
def poll_rss(feed: str | None, force: bool) -> None:
    """Poll RSS feeds and fetch discovered reports."""
    from gov_report.rss import poll_all_feeds, poll_feed
    from gov_report.pipeline import process_rss_items

    settings = get_settings()
    settings.ensure_dirs()
    if feed:
        items = _run(poll_feed(feed))
    else:
        items = _run(poll_all_feeds())
    if not items:
        console.print("[yellow]No new RSS items[/yellow]")
        return
    console.print(f"[blue]Discovered {len(items)} RSS item(s)[/blue]")
    results = _run(process_rss_items(settings, items, force=force))
    console.print(f"[green]Processed {len(results)} report(s)[/green]")


@cli.command()
def status() -> None:
    """Show fetch history and sync state."""
    from gov_report.sync_store import SyncStore

    settings = get_settings()
    store = SyncStore(settings.sync_db_path)
    rows = store.recent_fetches(limit=20)
    store.close()

    if not rows:
        console.print("[yellow]No fetch history yet[/yellow]")
        return

    table = Table(title="Recent Fetches")
    table.add_column("SHA", style="dim", max_width=12)
    table.add_column("Source")
    table.add_column("Date")
    table.add_column("Status")
    table.add_column("Fetched At")

    for row in rows:
        table.add_row(
            row["sha256"][:12],
            row["source_id"],
            row["publish_date"] or "",
            row["status"],
            row["fetched_at"],
        )
    console.print(table)


@cli.command("list-sources")
@click.option(
    "--country",
    type=click.Choice(["us", "cn", "all"]),
    default="all",
    help="Filter by country.",
)
def list_sources(country: str) -> None:
    """List all configured sources."""
    from gov_report.registry import SOURCES

    table = Table(title="Configured Sources")
    table.add_column("Source ID")
    table.add_column("Institution")
    table.add_column("Country")
    table.add_column("Category")

    for sid, cfg in sorted(SOURCES.items()):
        if country != "all" and cfg.country.lower() != country:
            continue
        table.add_row(sid, cfg.institution, cfg.country, cfg.data_category)
    console.print(table)
