# Macro Data Layer

Centralized economic data layer for agent-driven macro research. FRED-first implementation — a Python library that Maxwell (or any Python caller) imports directly.

## Quick Start

```python
from src import MacroDataLayer

dl = MacroDataLayer()

# Latest CPI data
cpi = dl.get("CPI", "US")

# Date-filtered
cpi_2024 = dl.get("CPI", "US", start="2024-01-01", end="2024-12-31")

# Year-over-year inflation (FRED computes server-side)
inflation = dl.get("CPI", "US", start="2024-01-01", units="pc1")

# What was GDP known to be on Jan 31, 2024?
gdp_vintage = dl.get_vintage("GDP_REAL", "US", as_of="2024-01-31")

# Full revision history
gdp_revisions = dl.get_revisions("GDP_REAL", "US")

# List all indicators
dl.list_indicators()
dl.list_indicators("inflation")

# Metadata + sync status
dl.describe("CPI")
```

## Architecture

```
MacroDataLayer          ← agent entry point
├── Registry            ← 46 canonical indicators → FRED series IDs
├── Storage (SQLite)    ← local cache: macro_series, alfred_vintages, sync_log
└── FREDProvider        ← fredapi wrapper with retry
```

**Local-first reads with lazy refresh.** `get()` checks the sync_log TTL — if stale, it fetches from FRED (with a revision-aware lookback window), upserts into SQLite, then returns from the local DB. Subsequent reads within the TTL window hit only SQLite (~2ms).

## Project Structure

```
macro_data_layer/
├── pyproject.toml
├── .env                         # FRED_API_KEY
├── config/
│   └── data_layer.yaml          # provider settings, TTLs
├── src/
│   ├── __init__.py              # exports MacroDataLayer
│   ├── data_layer.py            # MacroDataLayer class
│   ├── storage.py               # SQLite operations
│   ├── registry.py              # indicator registry (46 FRED series)
│   └── providers/
│       ├── base.py              # BaseProvider ABC + retry
│       └── fred.py              # FREDProvider
├── data/
│   └── macro_data.db            # ~40 MB bootstrapped
└── tests/
    ├── test_storage.py          # SQLite CRUD (no API calls)
    ├── test_registry.py         # registry lookups
    ├── test_fred_provider.py    # FRED API integration
    └── test_data_layer.py       # end-to-end
```

## API Reference

### `get(indicator, country="US", start=None, end=None, units=None)`

Returns a DataFrame of time-series data. Local-first with lazy refresh.

The `units` parameter applies a FRED server-side transformation (fetched live, not cached):

| Value | Meaning |
|-------|---------|
| `None` | Raw levels (default, cached locally) |
| `"chg"` | Change from previous value |
| `"ch1"` | Change from year ago |
| `"pch"` | Percent change |
| `"pc1"` | Percent change from year ago |
| `"pca"` | Compounded annual rate of change |
| `"log"` | Natural log |

### `get_vintage(indicator, country="US", as_of=None)`

Point-in-time query from ALFRED data. Returns what was known as of a given date. Only works for ALFRED-tracked indicators (16 series with revision history).

### `get_revisions(indicator, country="US")`

Full revision history for an ALFRED-tracked indicator.

### `list_indicators(category=None)`

Returns a DataFrame of all registered indicators. Optional category filter.

### `describe(indicator, country="US")`

Returns metadata dict: canonical name, description, frequency, FRED ID, sync status.

### `refresh(indicator=None, country=None)`

Explicit refresh. Without args, refreshes all stale series. Returns summary dict.

### `bootstrap()`

One-time full data load: all 46 FRED series + 16 ALFRED revision histories. Takes ~2 minutes.

## Indicators

46 FRED series across 10 categories:

| Category | Indicators |
|----------|-----------|
| **Output** | GDP, GDP_REAL, GDP_GROWTH |
| **Inflation** | CPI, CORE_CPI, PCE, CORE_PCE, PPI |
| **Employment** | NFP, UNEMPLOYMENT, INITIAL_CLAIMS, CONTINUING_CLAIMS, AVG_WEEKLY_HOURS, AVG_HOURLY_EARNINGS, JOLTS, MFG_EMPLOYMENT |
| **Consumer** | RETAIL_SALES, CONSUMER_SENTIMENT, CONSUMER_CONFIDENCE, PCE_SPENDING |
| **Manufacturing** | INDUSTRIAL_PROD, CAPACITY_UTIL, DURABLE_GOODS, MFG_NEW_ORDERS |
| **Housing** | HOUSING_STARTS, BUILDING_PERMITS, HOME_PRICE_INDEX, EXISTING_HOME_SALES, NEW_HOME_SALES |
| **Rates** | POLICY_RATE, POLICY_RATE_DAILY, TREASURY_2Y, TREASURY_10Y, TREASURY_30Y, YIELD_CURVE_10Y2Y, YIELD_CURVE_10Y3M, HY_SPREAD |
| **Money** | M2, MONETARY_BASE, FED_BALANCE_SHEET |
| **Trade** | TRADE_BALANCE, NET_EXPORTS |
| **Financial** | SP500, VIX, USD_INDEX, OIL_WTI |

16 of these are ALFRED-tracked (revision history stored): GDP, GDP_REAL, CPI, CORE_CPI, PCE, CORE_PCE, PPI, NFP, UNEMPLOYMENT, JOLTS, RETAIL_SALES, CONSUMER_SENTIMENT, PCE_SPENDING, INDUSTRIAL_PROD, DURABLE_GOODS, HOUSING_STARTS.

## Refresh Behavior

- **Lazy refresh**: `get()` checks TTL (24h for daily/monthly, 168h for weekly/quarterly). If stale, fetches incrementally from FRED before returning.
- **Revision-aware lookback**: monthly series re-fetch 90 days back, quarterly 180 days back, so revised values (e.g., GDP advance → final) are picked up via upsert.
- **Daily/weekly series**: no lookback (not revised).

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Set your FRED API key in `.env`:
```
FRED_API_KEY=your_key_here
```

Bootstrap the database:
```python
from src import MacroDataLayer
dl = MacroDataLayer()
dl.bootstrap()
```

Run tests:
```bash
.venv/bin/pytest tests/ -v
```

## Database Schema

Three tables in `data/macro_data.db`:

- **`macro_series`** — `(series_key, date, value, source, series_id, updated_at)` — PK on `(series_key, date)`
- **`alfred_vintages`** — `(series_id, date, realtime_start, value)` — PK on `(series_id, date, realtime_start)`
- **`sync_log`** — `(series_key, last_local_date, last_refresh, refresh_count, error_count)` — PK on `series_key`

## Future Phases

Not yet implemented:

- IMF, OECD, ECB, World Bank providers (global coverage)
- yfinance provider (gold, market data, calendar events)
- Validation layer
- Source router with fallback chains
- Parquet export
