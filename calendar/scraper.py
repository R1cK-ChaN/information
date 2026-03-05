"""
scraper.py — Investing.com economic calendar scraper.

Scrapes via their internal AJAX endpoint using cloudscraper to handle Cloudflare.
Falls back to full-page HTML parse if the API fails.

Usage:
    python scraper.py                  # scrape today, print to stdout
    python scraper.py --store          # scrape today and save to SQLite
    python scraper.py --from 2026-03-01 --to 2026-03-07 --store
"""

import cloudscraper
import hashlib
from datetime import datetime, timezone
from typing import List, Dict
from bs4 import BeautifulSoup

from store import init_db, upsert_event

# ─── Investing.com country IDs ───

COUNTRY_IDS = {
    5: "US", 72: "EU", 35: "JP", 4: "UK",
    17: "CA", 25: "AU", 6: "CN", 36: "NZ",
    12: "CH", 26: "SG", 34: "DE", 22: "FR",
}

CURRENCY_TO_COUNTRY = {
    "USD": "US", "EUR": "EU", "GBP": "UK", "JPY": "JP",
    "CAD": "CA", "AUD": "AU", "NZD": "NZ", "CHF": "CH",
    "CNY": "CN", "SGD": "SG",
}

# ─── Auto-categorisation keywords ───

CATEGORIES = {
    "inflation":       ["CPI", "PPI", "PCE", "Inflation", "Price Index"],
    "employment":      ["NFP", "Nonfarm", "Unemployment", "Jobless", "Employment", "ADP", "Payroll"],
    "growth":          ["GDP", "Retail Sales", "Industrial Production", "PMI", "ISM"],
    "monetary_policy": ["Interest Rate", "Fed", "FOMC", "ECB", "BOJ", "BOE", "Central Bank"],
    "housing":         ["Housing", "Home Sales", "Building Permits"],
    "consumer":        ["Consumer Confidence", "Consumer Sentiment", "Michigan"],
    "trade":           ["Trade Balance", "Current Account", "Import", "Export"],
}


def _categorize(name: str) -> str:
    upper = name.upper()
    for cat, keywords in CATEGORIES.items():
        if any(kw.upper() in upper for kw in keywords):
            return cat
    return "other"


def _event_id(country: str, indicator: str, dt: str) -> str:
    return hashlib.md5(f"{country}-{indicator}-{dt}".encode()).hexdigest()[:12]


def _clean(val: str):
    """Return None for empty / non-breaking-space values."""
    if not val or val in ("\xa0", " "):
        return None
    return val


# ─── Scraper ───

AJAX_URL = "https://www.investing.com/economic-calendar/Service/getCalendarFilteredData"
AJAX_HEADERS = {
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.investing.com/economic-calendar/",
}


def scrape(
    date_from: str = None,
    date_to: str = None,
    countries: List[str] = None,
) -> List[Dict]:
    """
    Scrape the Investing.com economic calendar.

    Args:
        date_from: 'YYYY-MM-DD'. Defaults to today (UTC).
        date_to:   'YYYY-MM-DD'. Defaults to date_from.
        countries: Country codes to include, e.g. ["US","EU"].
                   Defaults to US + G10 + CN + SG.

    Returns:
        List of event dicts.
    """
    if not date_from:
        date_from = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not date_to:
        date_to = date_from

    target = countries or ["US", "EU", "JP", "UK", "CA", "AU", "CN", "SG"]
    inv_ids = [k for k, v in COUNTRY_IDS.items() if v in target]

    session = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )

    # Try AJAX endpoint first
    events = _scrape_ajax(session, date_from, date_to, inv_ids)
    if not events:
        events = _scrape_page(session)
    return events


def _scrape_ajax(session, date_from, date_to, inv_ids) -> List[Dict]:
    try:
        resp = session.post(
            AJAX_URL,
            data={
                "dateFrom": date_from,
                "dateTo": date_to,
                "country[]": inv_ids,
                "importance[]": [1, 2, 3],
                "timeZone": 55,  # UTC
                "timeFilter": "timeRemain",
                "currentTab": "custom",
                "limit_from": 0,
            },
            headers=AJAX_HEADERS,
            timeout=30,
        )
        if resp.status_code != 200:
            return []
        html = resp.json().get("data", "")
        return _parse(html) if html else []
    except Exception:
        return []


def _scrape_page(session) -> List[Dict]:
    try:
        resp = session.get(
            "https://www.investing.com/economic-calendar/",
            timeout=30,
        )
        if resp.status_code != 200:
            return []
        return _parse(resp.text)
    except Exception:
        return []


def _parse(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    fallback_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    events = []

    for row in soup.find_all("tr", class_="js-event-item"):
        try:
            # Datetime
            raw_dt = row.get("data-event-datetime", "")
            if raw_dt:
                dt_str = raw_dt.replace("/", "-").replace(" ", "T")
            else:
                time_td = row.find("td", class_="time")
                t = time_td.text.strip() if time_td else ""
                dt_str = f"{fallback_date}T{t}:00" if t else fallback_date

            # Country
            flag_td = row.find("td", class_="flagCur")
            country = ""
            if flag_td:
                currency = flag_td.get_text(strip=True)
                country = CURRENCY_TO_COUNTRY.get(currency, currency)

            # Importance
            sent_td = row.find("td", class_="sentiment")
            bulls = len(sent_td.find_all("i", class_="grayFullBullishIcon")) if sent_td else 0
            importance = {3: "high", 2: "medium"}.get(bulls, "low")

            # Indicator
            ev_td = row.find("td", class_="event")
            if not ev_td:
                continue
            a = ev_td.find("a")
            indicator = (a.text.strip() if a else ev_td.text.strip())
            if not indicator:
                continue

            # Values
            actual   = _clean((row.find("td", class_="act")  or {}).get_text(strip=True) if row.find("td", class_="act")  else "")
            forecast = _clean((row.find("td", class_="fore") or {}).get_text(strip=True) if row.find("td", class_="fore") else "")
            previous = _clean((row.find("td", class_="prev") or {}).get_text(strip=True) if row.find("td", class_="prev") else "")

            events.append({
                "event_id": _event_id(country, indicator, dt_str),
                "datetime_utc": dt_str,
                "country": country,
                "indicator": indicator,
                "category": _categorize(indicator),
                "importance": importance,
                "actual": actual,
                "forecast": forecast,
                "previous": previous,
            })
        except Exception:
            continue

    return events


def scrape_and_store(**kwargs) -> List[Dict]:
    """Scrape and persist to SQLite. Returns the event list."""
    init_db()
    events = scrape(**kwargs)
    for e in events:
        upsert_event(e)
    return events


# ─── CLI ───

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Investing.com economic calendar scraper")
    parser.add_argument("--from", dest="date_from", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--to", dest="date_to", help="End date (YYYY-MM-DD)")
    parser.add_argument("--country", nargs="*", help="Country codes, e.g. US EU JP")
    parser.add_argument("--store", action="store_true", help="Save to SQLite")
    args = parser.parse_args()

    if args.store:
        events = scrape_and_store(
            date_from=args.date_from,
            date_to=args.date_to,
            countries=args.country,
        )
    else:
        events = scrape(
            date_from=args.date_from,
            date_to=args.date_to,
            countries=args.country,
        )

    # Print table
    print(f"\n{'Imp':<5} {'Time':<20} {'Ctry':<5} {'Indicator':<50} {'Actual':>10} {'Fcst':>10} {'Prev':>10}")
    print("─" * 115)
    for e in events:
        imp = {"high": "HIGH", "medium": "MED", "low": "low"}.get(e["importance"], "?")
        print(
            f"{imp:<5} {e['datetime_utc']:<20} {e['country']:<5} "
            f"{e['indicator']:<50} {(e['actual'] or '-'):>10} "
            f"{(e['forecast'] or '-'):>10} {(e['previous'] or '-'):>10}"
        )
    print(f"\nTotal: {len(events)} events", end="")
    if args.store:
        print(" (stored to calendar.db)", end="")
    print()
