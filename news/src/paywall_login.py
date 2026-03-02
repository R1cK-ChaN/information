"""CLI entry point for one-time paywall login.

Usage:
    python -m src.paywall_login https://www.bloomberg.com

Opens a visible Chromium browser with the persistent profile so you can
log in manually.  Close the browser window when done — the session
cookies are saved automatically.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m src.paywall_login <url>")
        sys.exit(1)

    url = sys.argv[1]

    config_path = Path(__file__).resolve().parent.parent / "config" / "news_stream.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)

    pw_cfg = config.get("providers", {}).get("paywall_fetcher", {})
    domains = pw_cfg.get("domains", [])
    browser_data_dir = pw_cfg.get("browser_data_dir", "data/browser_profile")

    project_root = Path(__file__).resolve().parent.parent
    browser_data_dir = str(project_root / browser_data_dir)

    from .paywall_fetcher import PaywallFetcher

    fetcher = PaywallFetcher(
        paywall_domains=domains,
        browser_data_dir=browser_data_dir,
    )
    fetcher.login(url)


if __name__ == "__main__":
    main()
