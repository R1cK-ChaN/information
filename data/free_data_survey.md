# Macro Data Layer — Service Specification

## Centralized Data Interface for Agent-Driven Macro Research

**Author:** Rick Chan | **Target:** NUS Master's Quant Macro Research
**Cost:** $0/year | **Last Updated:** 2026-03-01
**Focus Countries:** US, G10 (EUR, GBP, JPY, CHF, CAD, AUD, NZD, NOK, SEK), China, Singapore

---

## Table of Contents

1. [Service Overview & Architecture](#1-service-overview--architecture)
2. [Agent Interface Specification](#2-agent-interface-specification)
3. [Data Categories & Indicator Registry](#3-data-categories--indicator-registry)
4. [Source Routing & Provider Backends](#4-source-routing--provider-backends)
5. [Local-First Storage & Refresh Strategy](#5-local-first-storage--refresh-strategy)
6. [Error Handling, Retry & Fallback](#6-error-handling-retry--fallback)
7. [Validation Layer](#7-validation-layer)
8. [Configuration Schema](#8-configuration-schema)
9. [Implementation Roadmap](#9-implementation-roadmap)
- [Appendix A: Provider Reference](#appendix-a-provider-reference)
- [Appendix B: Complete Series ID Registry](#appendix-b-complete-series-id-registry)
- [Appendix C: Country Code Reference](#appendix-c-country-code-reference)
- [Appendix D: API Keys & Package Summary](#appendix-d-api-keys--package-summary)

---

## 1. Service Overview & Architecture

### Design Goals

| Goal | Description |
|---|---|
| **Agent-first interface** | The macro analyst agent calls `dl.get("CPI", "US")` — it never touches `fredapi` or `sdmx` directly |
| **Indicator-first addressing** | Queries use canonical indicator names (e.g., `"GDP_REAL"`, `"CPI"`) not provider-specific series IDs |
| **Local-first storage** | Historical data stored permanently in local SQLite. External APIs only called for latest incremental data |
| **Auto fallback** | If primary provider fails, the DataLayer transparently routes to backup sources |
| **Zero cost** | 9 free data providers, no paid subscriptions required |

### Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                       MACRO ANALYST AGENT                           │
│                                                                     │
│   dl.get("CPI", "US")    dl.get_market("EURUSD")                   │
│   dl.get_calendar()       dl.get_vintage("GDP", "US", as_of=...)   │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                   ┌─────────▼──────────┐
                   │   MacroDataLayer   │  ← Python API surface
                   │   (Service Entry)  │
                   └─────────┬──────────┘
                             │
                   ┌─────────▼──────────┐
                   │  Local SQLite DB   │  ← PRIMARY data source
                   │  (macro_series,    │     Query here first.
                   │   market_prices,   │     ~99% of reads served
                   │   alfred_vintages, │     from local store.
                   │   calendar_events) │
                   └─────────┬──────────┘
                             │ cache miss (new data only)
                   ┌─────────▼──────────┐
                   │   SourceRouter     │  ← Routes to correct provider
                   │   (incremental     │     based on indicator + country
                   │    fetch only)     │
                   └─────────┬──────────┘
                             │
          ┌──────────┬───────┴────────┬──────────┐
          ▼          ▼                ▼          ▼
    ┌──────────┐ ┌────────┐   ┌──────────┐ ┌────────┐
    │  FRED /  │ │  IMF   │   │  OECD    │ │  ECB   │
    │  ALFRED  │ │IFS/WEO │   │ MEI/CLI  │ │  SDW   │
    └──────────┘ └────────┘   └──────────┘ └────────┘
    ┌──────────┐ ┌────────┐   ┌──────────┐ ┌────────┐ ┌──────────┐
    │ yfinance │ │Finnhub │   │Comtrade  │ │World   │ │ Nasdaq   │
    │(Markets) │ │(Cal)   │   │(Trade)   │ │Bank    │ │Data Link │
    └──────────┘ └────────┘   └──────────┘ └────────┘ └──────────┘
```

### Technology Stack

| Component | Tool | Why |
|---|---|---|
| Language | Python 3.10+ | Best ecosystem for data science + API clients |
| Data Storage | SQLite + Parquet | Zero cost, portable, fast for time-series |
| DataLayer API | `MacroDataLayer` class | Single entry point for all agent queries |
| Source Routing | `SourceRouter` + provider backends | Indicator→source mapping with fallback chains |
| Validation | `ValidationLayer` | Freshness, completeness, range checks (mirrors `fact_check.py` pattern) |
| Retry | Exponential backoff | 3 retries per request (mirrors `market_data.py:_retry()` pattern) |
| Config | YAML (`data_layer.yaml`) | Provider settings, cache backend, focus countries |
| Parallelism | `ThreadPoolExecutor` | Concurrent multi-source fetches |

---

## 2. Agent Interface Specification

### MacroDataLayer Class

```python
from macro_data_layer import MacroDataLayer

dl = MacroDataLayer("config/data_layer.yaml")
```

### Core Methods

#### `get(indicator, country, start=None, end=None, frequency=None) → DataFrame`

Fetch a macro indicator time series. Reads from local DB first; only calls external API for data after the last locally stored date.

```python
# US CPI, full history
cpi = dl.get("CPI", "US")

# Real GDP for multiple countries
gdp = dl.get("GDP_REAL", ["US", "GB", "JP"], start="2020-01-01")

# Core PCE (US-only indicator)
core_pce = dl.get("CORE_PCE", "US", start="2023-01-01", end="2025-12-31")
```

#### `get_market(symbol, start=None, end=None, interval="1d") → DataFrame`

Fetch market price data (FX, equity indices, commodities, bond ETFs).

```python
# G10 FX
eurusd = dl.get_market("EURUSD", start="2020-01-01")

# Multiple symbols
prices = dl.get_market(["SP500", "VIX", "GOLD", "WTI"], start="2024-01-01")
```

#### `get_calendar(start=None, end=None, country=None, impact=None) → DataFrame`

Fetch economic calendar events from Finnhub. Ephemeral data — not stored long-term.

```python
# Upcoming high-impact events
events = dl.get_calendar(impact="high")

# US events next 7 days
us_cal = dl.get_calendar(country="US")
```

#### `get_vintage(indicator, country, as_of) → DataFrame`

Get point-in-time data: what was the indicator value known to be on `as_of` date. Reads from local ALFRED vintage store. US indicators only (via FRED ALFRED).

```python
# What was GDP known to be on Jan 31 2024?
gdp_pit = dl.get_vintage("GDP", "US", as_of="2024-01-31")
```

#### `get_revisions(indicator, country) → DataFrame`

Get full revision history for an indicator. Returns all vintages stored locally.

```python
# Full revision history for GDP
revisions = dl.get_revisions("GDP_REAL", "US")
# Returns: date, realtime_start, value, revision_number
```

#### `list_indicators(category=None, country=None) → DataFrame`

List available indicators, optionally filtered by category or country coverage.

```python
# All available indicators
all_ind = dl.list_indicators()

# Inflation indicators available for Japan
jp_inflation = dl.list_indicators(category="inflation", country="JP")
```

#### `describe(indicator) → dict`

Get metadata for an indicator: canonical name, source, frequency, coverage, last update.

```python
info = dl.describe("CPI")
# {'canonical_name': 'CPI', 'description': 'Consumer Price Index (All Urban, SA)',
#  'frequency': 'monthly', 'us_source': 'FRED:CPIAUCSL',
#  'g10_source': 'IMF_IFS:PCPI_IX', 'last_updated': '2026-02-28', ...}
```

#### `refresh(indicator=None, country=None) → dict`

Manually trigger incremental refresh. Without arguments, refreshes all stale series.

```python
# Refresh specific series
dl.refresh("CPI", "US")

# Refresh everything that's due
result = dl.refresh()
# {'refreshed': 42, 'skipped': 180, 'failed': 1, 'errors': [...]}
```

### Return Format

All `get()` and `get_market()` methods return a pandas DataFrame with a standard schema:

| Column | Type | Description |
|---|---|---|
| `date` | datetime64 | Observation date (index) |
| `value` | float64 | Observed value |
| `source` | str | Provider that supplied this row (e.g., `"FRED"`, `"IMF_IFS"`) |
| `series_id` | str | Provider-specific series ID (e.g., `"CPIAUCSL"`, `"PCPI_IX"`) |

For multi-country queries, an additional `country` column (ISO2) is included.

For `get_market()`, the schema is:

| Column | Type | Description |
|---|---|---|
| `date` | datetime64 | Trading date (index) |
| `open` | float64 | Open price |
| `high` | float64 | High price |
| `low` | float64 | Low price |
| `close` | float64 | Close / last price |
| `volume` | float64 | Volume (where available) |
| `symbol` | str | Canonical symbol name |

### Error Behavior Contract

| Scenario | Default Behavior |
|---|---|
| Provider API down | Retry 3× with exponential backoff → try fallback source → serve stale cache with `stale=True` warning |
| Indicator not found | Raise `IndicatorNotFoundError` with suggestions from `list_indicators()` |
| Country not covered | Return empty DataFrame + `logging.warning` with available countries for that indicator |
| Rate limited | Retry with backoff, queue remaining requests |
| Network timeout | Retry 3× → return stale cache or empty DataFrame + warning |

---

## 3. Data Categories & Indicator Registry

The canonical indicator registry maps human-readable names to provider-specific series IDs. The agent uses canonical names only — the SourceRouter resolves them to provider calls.

### Output & Growth

| Canonical Name | Description | US Source (Series ID) | G10 Source (Code) | CN/SG Source | Freq | Cache TTL |
|---|---|---|---|---|---|---|
| `GDP` | Nominal GDP | FRED (`GDP`) | IMF IFS (`NGDP`) | IMF IFS | Q | 7d |
| `GDP_REAL` | Real GDP | FRED (`GDPC1`) | IMF IFS (`NGDP_R`) | IMF IFS | Q | 7d |
| `GDP_GROWTH` | Real GDP Growth Rate | FRED (`A191RL1Q225SBEA`) | IMF WEO (`NGDP_RPCH`) | IMF WEO | Q/A | 7d |

### Inflation

| Canonical Name | Description | US Source (Series ID) | G10 Source (Code) | CN/SG Source | Freq | Cache TTL |
|---|---|---|---|---|---|---|
| `CPI` | Consumer Price Index | FRED (`CPIAUCSL`) | IMF IFS (`PCPI_IX`) | IMF IFS | M | 1d |
| `CPI_YOY` | CPI Year-over-Year % | FRED (derived) | IMF IFS (`PCPI_PC_CP_A_PT`) | IMF IFS | M | 1d |
| `CORE_CPI` | Core CPI (ex Food & Energy) | FRED (`CPILFESL`) | OECD (`PRICES_CPI`) | — | M | 1d |
| `PCE` | PCE Price Index | FRED (`PCEPI`) | — | — | M | 1d |
| `CORE_PCE` | Core PCE | FRED (`PCEPILFE`) | — | — | M | 1d |
| `PPI` | Producer Price Index | FRED (`PPIFIS`) | IMF IFS (`PPPI_IX`) | IMF IFS | M | 1d |

### Employment

| Canonical Name | Description | US Source (Series ID) | G10 Source (Code) | CN/SG Source | Freq | Cache TTL |
|---|---|---|---|---|---|---|
| `NFP` | Nonfarm Payrolls | FRED (`PAYEMS`) | — | — | M | 1d |
| `UNEMPLOYMENT` | Unemployment Rate | FRED (`UNRATE`) | IMF IFS (`LUR_PT`) | IMF IFS | M/Q | 1d |
| `INITIAL_CLAIMS` | Initial Jobless Claims | FRED (`ICSA`) | — | — | W | 1d |
| `CONTINUING_CLAIMS` | Continuing Claims | FRED (`CCSA`) | — | — | W | 1d |
| `AVG_WEEKLY_HOURS` | Avg Weekly Hours (Private) | FRED (`AWHAETP`) | — | — | M | 1d |
| `AVG_HOURLY_EARNINGS` | Avg Hourly Earnings (Private) | FRED (`CES0500000003`) | — | — | M | 1d |
| `JOLTS` | Job Openings (JOLTS) | FRED (`JTSJOL`) | — | — | M | 1d |
| `MFG_EMPLOYMENT` | Manufacturing Employment | FRED (`MANEMP`) | — | — | M | 1d |

### Consumer

| Canonical Name | Description | US Source (Series ID) | G10 Source (Code) | CN/SG Source | Freq | Cache TTL |
|---|---|---|---|---|---|---|
| `RETAIL_SALES` | Retail Sales (Total) | FRED (`RSAFS`) | — | — | M | 1d |
| `CONSUMER_SENTIMENT` | Michigan Consumer Sentiment | FRED (`UMCSENT`) | — | — | M | 1d |
| `CONSUMER_CONFIDENCE` | Consumer Confidence | FRED (`CSCICP03USM665S`) | OECD (`CCI`) | — | M | 7d |
| `PCE_SPENDING` | Personal Consumption Expenditure | FRED (`PCE`) | — | — | M | 1d |

### Manufacturing

| Canonical Name | Description | US Source (Series ID) | G10 Source (Code) | CN/SG Source | Freq | Cache TTL |
|---|---|---|---|---|---|---|
| `INDUSTRIAL_PROD` | Industrial Production Index | FRED (`INDPRO`) | IMF IFS (`AIP_IX`) | IMF IFS | M | 1d |
| `CAPACITY_UTIL` | Capacity Utilization | FRED (`TCU`) | — | — | M | 1d |
| `DURABLE_GOODS` | Durable Goods Orders | FRED (`DGORDER`) | — | — | M | 1d |
| `MFG_NEW_ORDERS` | Manufacturers New Orders | FRED (`NEWORDER`) | — | — | M | 1d |

### Housing

| Canonical Name | Description | US Source (Series ID) | G10 Source (Code) | CN/SG Source | Freq | Cache TTL |
|---|---|---|---|---|---|---|
| `HOUSING_STARTS` | Housing Starts | FRED (`HOUST`) | — | — | M | 1d |
| `BUILDING_PERMITS` | Building Permits | FRED (`PERMIT`) | — | — | M | 1d |
| `HOME_PRICE_INDEX` | Case-Shiller Home Price Index | FRED (`CSUSHPISA`) | — | — | M | 7d |
| `EXISTING_HOME_SALES` | Existing Home Sales | FRED (`EXHOSLUSM495S`) | — | — | M | 1d |
| `NEW_HOME_SALES` | New Home Sales | FRED (`NHSUSSPT`) | — | — | M | 1d |

### Interest Rates

| Canonical Name | Description | US Source (Series ID) | G10 Source (Code) | CN/SG Source | Freq | Cache TTL |
|---|---|---|---|---|---|---|
| `POLICY_RATE` | Policy Interest Rate | FRED (`FEDFUNDS`) | IMF IFS (`FPOLM_PA`) | IMF IFS | M/D | 1d |
| `POLICY_RATE_DAILY` | Fed Funds Rate (Daily) | FRED (`DFF`) | — | — | D | 1d |
| `TREASURY_2Y` | 2-Year Treasury Yield | FRED (`DGS2`) | — | — | D | 1d |
| `TREASURY_10Y` | 10-Year Treasury Yield | FRED (`DGS10`) | — | — | D | 1d |
| `TREASURY_30Y` | 30-Year Treasury Yield | FRED (`DGS30`) | — | — | D | 1d |
| `YIELD_CURVE_10Y2Y` | 10Y-2Y Spread | FRED (`T10Y2Y`) | — | — | D | 1d |
| `YIELD_CURVE_10Y3M` | 10Y-3M Spread | FRED (`T10Y3M`) | — | — | D | 1d |
| `HY_SPREAD` | US High Yield OAS | FRED (`BAMLH0A0HYM2`) | — | — | D | 1d |
| `ECB_REFI_RATE` | ECB Main Refinancing Rate | — | ECB (`FM:D.U2.EUR.4F.KR.MRR_FR.LEV`) | — | D | 1d |
| `DEPOSIT_RATE` | Deposit Rate | — | IMF IFS (`FIDR_PA`) | IMF IFS | M | 7d |
| `LENDING_RATE` | Lending Rate | — | IMF IFS (`FILR_PA`) | IMF IFS | M | 7d |
| `EA_BOND_10Y` | Euro Area 10Y Gov Bond | — | ECB (`YC:B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y`) | — | D | 1d |

### Money & Credit

| Canonical Name | Description | US Source (Series ID) | G10 Source (Code) | CN/SG Source | Freq | Cache TTL |
|---|---|---|---|---|---|---|
| `M2` | M2 Money Supply | FRED (`M2SL`) | IMF IFS (`FMB_XDC`) | IMF IFS | M | 7d |
| `MONETARY_BASE` | Monetary Base | FRED (`BOGMBASE`) | — | — | M | 7d |
| `FED_BALANCE_SHEET` | Fed Total Assets | FRED (`WALCL`) | — | — | W | 1d |
| `M3_EURO` | Euro Area M3 | — | ECB (`BSI:M.U2.N.V.M30.X.1.U2.2300.Z01.E`) | — | M | 7d |

### External

| Canonical Name | Description | US Source (Series ID) | G10 Source (Code) | CN/SG Source | Freq | Cache TTL |
|---|---|---|---|---|---|---|
| `TRADE_BALANCE` | Trade Balance (Goods & Services) | FRED (`BOPGSTB`) | IMF BOP (`BCA`) | IMF BOP | M/Q | 7d |
| `CURRENT_ACCOUNT` | Current Account Balance | FRED (`BOPGSTB`) | IMF BOP (`BCA`) | IMF BOP | Q | 7d |
| `NET_EXPORTS` | Net Exports | FRED (`NETEXP`) | — | — | Q | 7d |
| `FX_RESERVES` | Foreign Exchange Reserves | — | IMF IFS (`RAFA`) | IMF IFS | M | 7d |
| `EXCHANGE_RATE` | Exchange Rate (per USD) | — | IMF IFS (`ENDA_XDC_USD_RATE`) | IMF IFS | M | 7d |
| `FDI` | Foreign Direct Investment (% GDP) | World Bank (`BX.KLT.DINV.WD.GD.ZS`) | World Bank | World Bank | A | 30d |
| `GOV_DEBT` | Government Debt (% GDP) | IMF WEO (`GGXWDG_NGDP`) | IMF WEO | IMF WEO | A | 30d |
| `TRADE_FLOWS` | Bilateral Trade (import/export) | UN Comtrade | UN Comtrade | UN Comtrade | A/M | 30d |

### Leading Indicators

| Canonical Name | Description | US Source (Series ID) | G10 Source (Code) | CN/SG Source | Freq | Cache TTL |
|---|---|---|---|---|---|---|
| `CLI` | Composite Leading Indicator | OECD (`MEI_CLI:LI`) | OECD (`MEI_CLI:LI`) | OECD (CN only) | M | 7d |
| `BCI` | Business Confidence Index | OECD (`MEI_CLI:BCI`) | OECD (`MEI_CLI:BCI`) | — | M | 7d |

### Market Data Symbols

| Canonical Symbol | Asset Class | yfinance Ticker | Backup |
|---|---|---|---|
| `EURUSD` | FX | `EURUSD=X` | ECB SDW |
| `GBPUSD` | FX | `GBPUSD=X` | ECB SDW |
| `USDJPY` | FX | `JPY=X` | ECB SDW |
| `USDCHF` | FX | `CHF=X` | ECB SDW |
| `USDCAD` | FX | `CAD=X` | ECB SDW |
| `AUDUSD` | FX | `AUDUSD=X` | ECB SDW |
| `NZDUSD` | FX | `NZDUSD=X` | ECB SDW |
| `USDNOK` | FX | `NOK=X` | ECB SDW |
| `USDSEK` | FX | `SEK=X` | ECB SDW |
| `USDCNY` | FX | `CNY=X` | ECB SDW |
| `USDSGD` | FX | `SGD=X` | ECB SDW |
| `SP500` | Equity Index | `^GSPC` | FRED (`SP500`) |
| `NASDAQ` | Equity Index | `^IXIC` | — |
| `DOW` | Equity Index | `^DJI` | — |
| `FTSE100` | Equity Index | `^FTSE` | — |
| `DAX` | Equity Index | `^GDAXI` | — |
| `NIKKEI` | Equity Index | `^N225` | — |
| `HSI` | Equity Index | `^HSI` | — |
| `SSE` | Equity Index | `000001.SS` | — |
| `STI` | Equity Index | `^STI` | — |
| `ASX200` | Equity Index | `^AXJO` | — |
| `TSX` | Equity Index | `^GSPTSE` | — |
| `SMI` | Equity Index | `^SSMI` | — |
| `VIX` | Volatility | `^VIX` | FRED (`VIXCLS`) |
| `GOLD` | Commodity | `GC=F` | FRED (`GOLDAMGBD228NLBM`) |
| `SILVER` | Commodity | `SI=F` | — |
| `WTI` | Commodity | `CL=F` | FRED (`DCOILWTICO`) |
| `BRENT` | Commodity | `BZ=F` | — |
| `NATGAS` | Commodity | `NG=F` | — |
| `COPPER` | Commodity | `HG=F` | — |
| `CORN` | Commodity | `ZC=F` | — |
| `WHEAT` | Commodity | `ZW=F` | — |
| `SOYBEANS` | Commodity | `ZS=F` | — |
| `UST_SHORT` | Bond ETF | `SHY` | — |
| `UST_MID` | Bond ETF | `IEF` | — |
| `UST_LONG` | Bond ETF | `TLT` | — |
| `UST_TIPS` | Bond ETF | `TIP` | — |
| `IG_CORP` | Bond ETF | `LQD` | — |
| `HY_CORP` | Bond ETF | `HYG` | — |
| `USD_INDEX` | FX Index | `DX-Y.NYB` | FRED (`DTWEXBGS`) |

---

## 4. Source Routing & Provider Backends

### Provider Summary

| Provider | Class Name | Coverage | Auth | Rate Limit | Package |
|---|---|---|---|---|---|
| FRED / ALFRED | `FREDProvider` | 840K+ US series, revision history | API key | 120 req/min | `fredapi` |
| IMF IFS/WEO/BOP | `IMFProvider` | 190+ countries, 20+ databases | None (optional) | 10 req/sec | `sdmx1` |
| OECD MEI/CLI | `OECDProvider` | 38 OECD members (all G10) | None | ~10 req/sec | `sdmx1` |
| ECB SDW | `ECBProvider` | Euro area + EU members | None | ~10 req/sec | `sdmx1` |
| Yahoo Finance | `YFinanceProvider` | Global FX, equities, commodities, bonds | None | Unofficial, no SLA | `yfinance` |
| Finnhub | `FinnhubProvider` | Economic calendar, news | API key | 60 req/min (free) | `finnhub-python` |
| UN Comtrade | `ComtradeProvider` | 200+ countries, bilateral trade | API key | 500 req/day | `comtradeapicall` |
| World Bank | `WorldBankProvider` | 200+ countries, 1,600+ dev indicators | None | Generous | `wbgapi` |
| Nasdaq Data Link | `NasdaqProvider` | FRED mirror + supplementary | API key | 50K req/day | `nasdaqdatalink` |

### Routing Logic

The `SourceRouter` maps `(indicator, country)` → provider call. Example resolution paths:

```
dl.get("CPI", "US")          → FREDProvider.fetch("CPIAUCSL")
dl.get("CPI", "GB")          → IMFProvider.fetch("IFS", "M.GB.PCPI_IX")
dl.get("CPI", "DE")          → IMFProvider.fetch("IFS", "M.DE.PCPI_IX")  [fallback: OECD PRICES_CPI]
dl.get("CLI", "US")          → OECDProvider.fetch("MEI_CLI", "USA.LI.AMPLITUD.M")
dl.get("GDP_REAL", "JP")     → IMFProvider.fetch("IFS", "Q.JP.NGDP_R")  [fallback: OECD QNA]
dl.get("GOV_DEBT", "CN")     → IMFProvider.fetch("WEO", "A.CN.GGXWDG_NGDP") [fallback: WorldBank]
dl.get_market("EURUSD")      → YFinanceProvider.fetch("EURUSD=X")       [fallback: ECB SDW EXR]
dl.get_calendar()             → FinnhubProvider.fetch_calendar()
dl.get_vintage("GDP", "US")  → FREDProvider.fetch_alfred("GDP")
```

### BaseProvider Interface

All provider backends implement this abstract interface:

```python
from abc import ABC, abstractmethod
import pandas as pd
import time
import logging

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds (base for exponential backoff)

class BaseProvider(ABC):
    """Abstract base for all data provider backends."""

    @abstractmethod
    def fetch(self, series_key: str, start: str = None, end: str = None) -> pd.DataFrame:
        """Fetch a single series. Returns standard schema DataFrame."""
        ...

    @abstractmethod
    def supports(self, indicator: str, country: str) -> bool:
        """Return True if this provider can supply the given indicator+country."""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """e.g. 'FRED', 'IMF_IFS', 'OECD'"""
        ...

    def fetch_with_retry(self, series_key: str, **kwargs) -> pd.DataFrame:
        """Retry a fetch call with exponential backoff.
        Mirrors the _retry() pattern from daily_stock_report/market_data.py.
        """
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return self.fetch(series_key, **kwargs)
            except Exception as e:
                if attempt == MAX_RETRIES:
                    raise
                logger.warning(
                    "[%s] Attempt %d/%d failed for %s: %s. Retrying...",
                    self.provider_name, attempt, MAX_RETRIES, series_key, e
                )
                time.sleep(RETRY_DELAY * attempt)
```

### Fallback Chains

When the primary provider fails after all retries, the router tries backup sources:

| Indicator Group | Primary → Fallback Chain |
|---|---|
| US macro (CPI, GDP, NFP, etc.) | FRED → Nasdaq Data Link (FRED mirror) |
| G10 macro (CPI, GDP, unemployment) | IMF IFS → OECD → (no further fallback) |
| CN/SG macro | IMF IFS → World Bank (annual only) |
| Leading indicators (CLI, BCI) | OECD → (no fallback — OECD is sole source) |
| FX rates | yfinance → ECB SDW (EUR crosses) → IMF IFS (monthly) |
| Equity indices | yfinance → (no fallback) |
| Commodities | yfinance → FRED (oil, gold only) |
| Economic calendar | Finnhub → (no fallback) |
| Trade flows | UN Comtrade → IMF DOTS |
| Government debt, FDI | IMF WEO → World Bank |
| Revision history (ALFRED) | FRED ALFRED → (no alternative — unique source) |

---

## 5. Local-First Storage & Refresh Strategy

### Core Principle: "Fetch Once, Store Forever"

Historical macro data (e.g., US CPI for Jan 2020) is immutable once published. There is no reason to re-fetch it. The DataLayer treats the local database as the **primary** data source, not external APIs.

### Read Path

```
Agent calls dl.get("CPI", "US", start="2020-01-01")
  → Query local SQLite first (covers all stored history)
  → Only call external API for data AFTER the last locally stored date
  → Append new data to local store
  → Return full result from local store
```

### Write/Sync Path (Incremental Append Only)

```
dl.refresh("CPI", "US")
  → Find last stored date for this series (e.g., 2026-01-31)
  → Fetch from API only start=2026-02-01 onward
  → Append to local DB
  → ~99% of queries never hit external APIs
```

### Initial Bootstrap

- **First run:** full historical pull from API → store locally (one-time cost)
- **Subsequent runs:** incremental append only (fast, minimal API calls)

### Storage Schema

**SQLite tables:**

```sql
-- Core macro time series
CREATE TABLE macro_series (
    series_key  TEXT NOT NULL,   -- e.g. "CPI:US", "GDP_REAL:JP"
    date        TEXT NOT NULL,   -- ISO date
    value       REAL,
    source      TEXT NOT NULL,   -- e.g. "FRED", "IMF_IFS"
    series_id   TEXT NOT NULL,   -- provider-specific ID
    updated_at  TEXT NOT NULL,   -- when this row was written
    PRIMARY KEY (series_key, date)
);

-- Market prices (OHLCV)
CREATE TABLE market_prices (
    symbol      TEXT NOT NULL,   -- canonical symbol, e.g. "EURUSD", "SP500"
    date        TEXT NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    volume      REAL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (symbol, date)
);

-- ALFRED revision vintages (US only)
CREATE TABLE alfred_vintages (
    series_id       TEXT NOT NULL,   -- e.g. "GDP", "CPIAUCSL"
    date            TEXT NOT NULL,   -- observation date
    realtime_start  TEXT NOT NULL,   -- when this vintage was published
    value           REAL,
    PRIMARY KEY (series_id, date, realtime_start)
);
CREATE INDEX idx_alfred_lookup ON alfred_vintages(series_id, date, realtime_start);

-- Economic calendar (ephemeral, rolling window)
CREATE TABLE calendar_events (
    event_id    TEXT PRIMARY KEY,
    country     TEXT,
    event       TEXT,
    time        TEXT,
    impact      TEXT,
    actual      REAL,
    estimate    REAL,
    prev        REAL,
    unit        TEXT,
    fetched_at  TEXT NOT NULL
);

-- Sync metadata (tracks last refresh per series)
CREATE TABLE sync_log (
    series_key      TEXT PRIMARY KEY,
    last_local_date TEXT,       -- latest date stored locally
    last_refresh    TEXT,       -- when we last called the API
    refresh_count   INTEGER DEFAULT 0,
    error_count     INTEGER DEFAULT 0
);
```

**Parquet exports** for large analytical queries: the DataLayer can export any table to Parquet for use with pandas/pyarrow on large datasets.

### ALFRED Revisions

All vintages stored locally. Once captured, revision data is immutable. `get_vintage()` and `get_revisions()` read from local DB only (after initial bootstrap).

Bootstrap pulls full revision history via `fred.get_series_all_releases()` for tracked series:
`GDP`, `GDPC1`, `CPIAUCSL`, `CPILFESL`, `PCEPI`, `PCEPILFE`, `PAYEMS`, `UNRATE`, `RSAFS`, `INDPRO`, `HOUST`, `DGORDER`, `UMCSENT`, `JTSJOL`, `PCE`, `PPIFIS`.

### Refresh Schedule

| Data Class | Refresh Frequency | What Gets Fetched |
|---|---|---|
| Daily market prices | Every trading day | Only today's close |
| Weekly series (claims, Fed BS) | Weekly | Only latest week |
| Monthly macro (CPI, NFP) | Daily check, ~monthly new data | Only new month's release |
| Quarterly macro (GDP, BOP) | Weekly check, ~quarterly new | Only new quarter's release |
| Annual (World Bank, WEO) | Monthly check | Only new year's data |
| Calendar events | Every 15 minutes | Upcoming 7 days (ephemeral, not stored long-term) |
| ALFRED vintages | Weekly | Only new vintages since last check |

### DIY Revision Tracking for Non-US Data

For non-US indicators (where ALFRED is unavailable), the DataLayer timestamps every download. Over time this builds a point-in-time database:

```python
# Internal to the refresh logic — every IMF/OECD fetch stores:
#   (series_key, date, value, download_timestamp)
# After 6+ months of daily refreshes, you have a revision log
# showing how values changed between successive publications.
```

---

## 6. Error Handling, Retry & Fallback

### Retry Policy

Mirrors the `_retry()` pattern from `daily_stock_report/src/fetchers/market_data.py`:

```python
def _retry(func, *args, **kwargs):
    """Retry a function call with exponential backoff."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if attempt == MAX_RETRIES:
                raise
            logger.warning("Attempt %d/%d failed: %s. Retrying...", attempt, MAX_RETRIES, e)
            time.sleep(RETRY_DELAY * attempt)
```

| Parameter | Value |
|---|---|
| `MAX_RETRIES` | 3 |
| `RETRY_DELAY` | 2 seconds (base) |
| Backoff formula | `RETRY_DELAY * attempt` (2s, 4s, 6s) |
| Timeout per request | 30 seconds |

### Fallback Strategy

When all retries for a primary provider are exhausted:

1. **Try fallback chain** — route the same indicator to the backup source (see Section 4 fallback chains)
2. **Serve stale cache** — if local DB has data for this series, return it with a `stale=True` flag and `logging.warning`
3. **Return empty** — if no cached data exists, return empty DataFrame with `logging.warning`
4. **Never raise to the agent** for transient failures — the agent should always get *something* back

### Known Limitations & Mitigations

| Limitation | Impact | Mitigation |
|---|---|---|
| No revision history for non-US data | Cannot build true point-in-time DB for G10/CN/SG | DIY revision tracking via timestamped downloads (Section 5) |
| yfinance is unofficial | May break without notice | Store all downloaded data locally; fallback to FRED for key series (VIX, oil, gold) |
| Finnhub calendar is basic | Missing some events, no historical calendar | Sufficient for upcoming-event awareness; historical calendar not needed for DataLayer |
| IMF SDMX learning curve | Complex API format | Abstracted behind `IMFProvider` — agent never sees SDMX |
| OECD doesn't cover China | No CLI for China | IMF IFS covers China for most indicators; no CLI equivalent |
| World Bank is annual only | Too low-freq for daily research | Use only for structural/long-term indicators (FDI, Gov Debt); IMF IFS for higher frequency |

### Degraded Mode

When operating in degraded mode (one or more providers down), the DataLayer:

- Continues serving all locally-cached data normally
- Logs which providers are unreachable
- Marks any returned series that couldn't be refreshed with `stale=True` metadata
- The agent can check `dl.health()` to see provider status

---

## 7. Validation Layer

Inspired by `daily_stock_report/src/checker/fact_check.py`, the validation layer runs pre- and post-fetch checks.

### ValidationResult

```python
@dataclass
class ValidationResult:
    passed: bool
    check_name: str        # e.g. "freshness", "range", "completeness"
    severity: str          # "error" | "warning" | "info"
    message: str
    details: dict = None   # optional metadata
```

### Pre-Fetch Validation

Run before returning data to the agent:

| Check | Logic | Severity |
|---|---|---|
| **Freshness** | Is the latest data point within expected staleness for this frequency? (e.g., monthly series should have data within last 45 days) | warning |
| **Completeness** | Are there unexpected gaps in the date range? (>2 consecutive missing periods) | warning |
| **Schema** | Does the DataFrame match the expected columns and types? | error |

### Post-Fetch Validation

Run after fetching new data from providers:

| Check | Logic | Severity |
|---|---|---|
| **Range** | Is the new value within a reasonable range for this indicator? (e.g., US unemployment rate should be 0-30%) | warning |
| **Spike detection** | Does the new value deviate >5 standard deviations from the trailing 12-month mean? | warning |
| **Duplicate detection** | Is this exact value+date already in the local store? | info (skip insert) |
| **Type coercion** | Can the returned value be safely cast to float? | error |

### Range Bounds (Configurable)

| Indicator | Min | Max | Unit |
|---|---|---|---|
| `UNEMPLOYMENT` | 0 | 30 | % |
| `CPI` (index) | 50 | 500 | index |
| `POLICY_RATE` | -2 | 25 | % |
| `GDP_GROWTH` | -25 | 25 | % |
| `VIX` | 5 | 100 | index |

---

## 8. Configuration Schema

The DataLayer is configured via `data_layer.yaml`, modeled on the existing `daily_stock_report/config/settings.yaml` pattern.

```yaml
# data_layer.yaml — Macro Data Layer Configuration

# ── General ──
timezone: "Asia/Singapore"
focus_countries: ["US", "GB", "JP", "DE", "FR", "CA", "AU", "NZ", "CH", "NO", "SE", "CN", "SG"]

# ── Storage ──
storage:
  sqlite_path: "data/macro_data.db"
  parquet_dir: "data/parquet/"
  enable_parquet_export: false    # export tables to parquet on refresh

# ── Provider API Keys (via environment variables) ──
providers:
  fred:
    api_key_env: "FRED_API_KEY"
    rate_limit: 120           # requests/minute
    enabled: true
  finnhub:
    api_key_env: "FINNHUB_API_KEY"
    rate_limit: 60
    enabled: true
  comtrade:
    api_key_env: "COMTRADE_API_KEY"
    rate_limit: 100           # requests/hour
    enabled: true
  nasdaq:
    api_key_env: "NASDAQ_API_KEY"
    rate_limit: 50000         # requests/day
    enabled: false            # disabled by default (redundant with FRED)
  imf:
    enabled: true
  oecd:
    enabled: true
  ecb:
    enabled: true
  worldbank:
    enabled: true
  yfinance:
    enabled: true

# ── Retry & Timeout ──
retry:
  max_retries: 3
  base_delay_seconds: 2       # exponential: delay * attempt
  request_timeout: 30         # seconds per request

# ── Refresh Schedule ──
refresh:
  market_prices: "daily"      # every trading day
  weekly_series: "weekly"     # claims, Fed balance sheet
  monthly_macro: "daily"      # check daily, new data ~monthly
  quarterly_macro: "weekly"
  annual_data: "monthly"
  calendar: "15min"
  alfred_vintages: "weekly"

# ── Validation ──
validation:
  enable_freshness_check: true
  enable_range_check: true
  enable_spike_detection: true
  spike_threshold_std: 5.0
  log_warnings: true          # log validation warnings

# ── Parallelism ──
parallel:
  max_workers: 4              # ThreadPoolExecutor threads for multi-source fetch
```

---

## 9. Implementation Roadmap

### Phase 1: Core (MVP)

Build the local-first storage, FRED provider, and agent interface.

- `MacroDataLayer` class with `get()`, `refresh()`, `list_indicators()`, `describe()`
- `FREDProvider` (highest coverage for US data)
- SQLite storage with `macro_series` and `sync_log` tables
- YAML config loading
- `_retry()` with exponential backoff

### Phase 2: Global Coverage

Add international providers and market data.

- `IMFProvider` (IFS + WEO + BOP) — covers G10, CN, SG
- `OECDProvider` (MEI_CLI) — leading indicators
- `ECBProvider` (SDW) — EUR rates, yields, M3
- `YFinanceProvider` — FX, equity indices, commodities, bond ETFs
- `get_market()` method
- `SourceRouter` with fallback chains

### Phase 3: Advanced Features

Add point-in-time data, calendar, and validation.

- `FREDProvider.fetch_alfred()` — revision history
- `get_vintage()`, `get_revisions()` methods
- `alfred_vintages` table + bootstrap logic
- `FinnhubProvider` — economic calendar
- `get_calendar()` method
- `ValidationLayer` — freshness, range, spike detection
- DIY revision tracking for non-US data

### Phase 4: Supplementary

Complete coverage and polish.

- `ComtradeProvider` — bilateral trade flows
- `WorldBankProvider` — annual development indicators
- `NasdaqProvider` — FRED mirror fallback
- Parquet export functionality
- `dl.health()` — provider status dashboard
- `ThreadPoolExecutor`-based parallel refresh

### Project Structure

```
macro_data_layer/
├── config/
│   ├── data_layer.yaml           # Main configuration
│   └── .env                      # API keys (git-ignored)
├── src/
│   ├── __init__.py
│   ├── data_layer.py             # MacroDataLayer class (agent entry point)
│   ├── router.py                 # SourceRouter (indicator→provider mapping)
│   ├── storage.py                # SQLite read/write, sync_log, Parquet export
│   ├── validation.py             # ValidationLayer + ValidationResult
│   ├── registry.py               # Indicator registry (canonical names → series IDs)
│   └── providers/
│       ├── __init__.py
│       ├── base.py               # BaseProvider ABC + fetch_with_retry()
│       ├── fred.py               # FREDProvider + ALFRED methods
│       ├── imf.py                # IMFProvider (IFS, WEO, BOP, DOTS)
│       ├── oecd.py               # OECDProvider (MEI_CLI, MEI, QNA)
│       ├── ecb.py                # ECBProvider (EXR, FM, BSI, YC)
│       ├── yfinance.py           # YFinanceProvider (FX, equity, commodity, bond ETF)
│       ├── finnhub.py            # FinnhubProvider (calendar, news)
│       ├── comtrade.py           # ComtradeProvider (bilateral trade)
│       ├── worldbank.py          # WorldBankProvider (annual dev indicators)
│       └── nasdaq.py             # NasdaqProvider (FRED mirror fallback)
├── data/
│   ├── macro_data.db             # SQLite database (git-ignored)
│   └── parquet/                  # Parquet exports (git-ignored)
├── tests/
│   ├── test_data_layer.py
│   ├── test_router.py
│   ├── test_storage.py
│   └── test_providers/
├── requirements.txt
└── pyproject.toml
```

---

## Appendix A: Provider Reference

Condensed reference for each of the 9 data providers. For setup and usage details, see the provider-specific code in `src/providers/`.

### A.1 FRED / ALFRED

| Attribute | Detail |
|---|---|
| **Provider** | Federal Reserve Bank of St. Louis |
| **URL** | https://fred.stlouisfed.org |
| **Coverage** | 840,000+ US economic time series from 118 sources |
| **Rate Limit** | 120 requests/minute |
| **Key Feature** | ALFRED vintage/revision data — the only free source with point-in-time history |
| **Auth** | API key required |

**Why FRED is the #1 source:** (1) ALFRED revision history — every data revision archived with timestamps, critical for backtesting without look-ahead bias. (2) Comprehensive US coverage — GDP, CPI, PPI, NFP, unemployment, ISM, housing, retail sales, industrial production, capacity utilization, yield curves, money supply, and hundreds more. (3) Official sources — data from BLS, BEA, Census Bureau, Fed, Treasury directly.

**Core fetch pattern:**
```python
from fredapi import Fred
fred = Fred(api_key='YOUR_KEY')

# Latest revised series
cpi = fred.get_series('CPIAUCSL', observation_start='2020-01-01')

# Point-in-time (ALFRED)
gdp_as_known = fred.get_series_as_of_date('GDP', '2024-01-31')
gdp_first_release = fred.get_series_first_release('GDP')
gdp_all_vintages = fred.get_series_all_releases('GDP')

# Search & metadata
results = fred.search('consumer price index')
info = fred.get_series_info('GDP')
```

### A.2 IMF Data API

| Attribute | Detail |
|---|---|
| **Provider** | International Monetary Fund |
| **URL** | https://data.imf.org |
| **Coverage** | 190+ countries, 20+ databases (IFS, WEO, BOP, DOTS, GFS, PCPS) |
| **Rate Limit** | 10 requests/second |
| **API** | SDMX 3.0 REST |
| **Auth** | None (optional beta portal key) |

**Core fetch pattern:**
```python
import sdmx
imf = sdmx.Client('IMF_DATA')

# Monthly CPI for multiple countries
data = imf.data('IFS', key='M.US+GB+JP+DE+CN+SG.PCPI_IX', params={'startPeriod': '2015'})
df = sdmx.to_pandas(data).reset_index()

# WEO annual GDP growth projections
data = imf.data('WEO', key='A.US+GB+JP.NGDP_RPCH', params={'startPeriod': '2020'})
```

**Key IFS indicator codes:** `PCPI_IX` (CPI), `PPPI_IX` (PPI), `NGDP` (nominal GDP), `NGDP_R` (real GDP), `AIP_IX` (industrial production), `LUR_PT` (unemployment), `FPOLM_PA` (policy rate), `ENDA_XDC_USD_RATE` (exchange rate), `BCA` (current account), `BTG` (trade balance), `RAFA` (reserves), `FMB_XDC` (broad money).

**Key WEO codes:** `NGDP_RPCH` (real GDP growth), `NGDPD` (GDP in USD), `PCPIPCH` (inflation avg), `LUR` (unemployment), `BCA_NGDPD` (current account % GDP), `GGXWDG_NGDP` (gov debt % GDP).

### A.3 OECD Data API

| Attribute | Detail |
|---|---|
| **Provider** | Organisation for Economic Co-operation and Development |
| **URL** | https://data-explorer.oecd.org |
| **Coverage** | 38 OECD members (all G10 included) |
| **Key Value** | Composite Leading Indicators (CLI) — predicts business cycle turning points 6-9 months ahead |
| **Auth** | None |

**Core fetch pattern:**
```python
import sdmx
oecd = sdmx.Client('OECD')

# CLI for G10 + China
data = oecd.data('MEI_CLI',
    key='USA+GBR+JPN+DEU+FRA+CAN+AUS+NZL+CHE+NOR+SWE+CHN.LI.AMPLITUD.M',
    params={'startPeriod': '2015-01'})

# Consumer / Business Confidence
data = oecd.data('MEI_CLI', key='USA+GBR+JPN+DEU.CCI.AMPLITUD.M', params={'startPeriod': '2015-01'})
data = oecd.data('MEI_CLI', key='USA+GBR+JPN+DEU.BCI.AMPLITUD.M', params={'startPeriod': '2015-01'})
```

**Key datasets:** `MEI_CLI` (CLI, CCI, BCI), `MEI` (industrial production, retail trade), `QNA` (quarterly GDP), `PRICES_CPI` (CPI by category), `STLABOUR` (employment), `KEI` (composite of all).

### A.4 ECB Statistical Data Warehouse

| Attribute | Detail |
|---|---|
| **Provider** | European Central Bank |
| **URL** | https://data.ecb.europa.eu |
| **Coverage** | Euro area + EU member states |
| **Key Value** | Official ECB exchange rates, interest rates, money supply, bond yields |
| **Auth** | None |

**Core fetch pattern:**
```python
import sdmx
ecb = sdmx.Client('ECB')

# EUR exchange rates
data = ecb.data('EXR', key='D.USD+GBP+JPY+CHF+CAD+AUD+NZD+NOK+SEK+CNY+SGD.EUR.SP00.A',
    params={'startPeriod': '2015-01-01'})

# ECB main refinancing rate
data = ecb.data('FM', key='D.U2.EUR.4F.KR.MRR_FR.LEV', params={'startPeriod': '2015-01-01'})

# Euro area M3
data = ecb.data('BSI', key='M.U2.N.V.M30.X.1.U2.2300.Z01.E', params={'startPeriod': '2015-01'})

# 10Y Euro area government bond yield
data = ecb.data('YC', key='B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y', params={'startPeriod': '2015-01-01'})
```

### A.5 Yahoo Finance (yfinance)

| Attribute | Detail |
|---|---|
| **Provider** | Yahoo Finance (unofficial API) |
| **Coverage** | Global equities, FX, commodities, crypto, indices, bonds |
| **Frequency** | 1min to monthly |
| **Warning** | Unofficial, no SLA — may break without notice |

**Core fetch pattern:**
```python
import yfinance as yf

# Single symbol
sp500 = yf.download('^GSPC', start='2000-01-01')

# Batch download
symbols = ['^GSPC', 'EURUSD=X', 'GC=F', '^VIX']
data = yf.download(symbols, start='2015-01-01', group_by='ticker')
```

See Section 3 (Market Data Symbols table) for complete symbol mappings.

### A.6 Finnhub

| Attribute | Detail |
|---|---|
| **Provider** | Finnhub.io |
| **Coverage** | Economic calendar (actual/forecast/previous), market news |
| **Rate Limit** | 60 calls/minute (free tier) |
| **Auth** | API key required |

**Core fetch pattern:**
```python
import finnhub
client = finnhub.Client(api_key="YOUR_KEY")

# Economic calendar (next 7 days)
calendar = client.economic_calendar(_from='2026-03-01', to='2026-03-08')
# Returns: country, event, time, impact, actual, estimate, prev, unit

# Filter high-impact events
high_impact = [e for e in calendar['economicCalendar'] if e.get('impact') == 'high']
```

**Limitations:** basic coverage vs paid services, no historical calendar, no WebSocket on free tier.

### A.7 UN Comtrade

| Attribute | Detail |
|---|---|
| **Provider** | United Nations Statistics Division |
| **URL** | https://comtradeplus.un.org |
| **Coverage** | 200+ countries, bilateral trade flows by commodity |
| **Rate Limit** | 500 requests/day, 100/hour |
| **Auth** | API key required |

**Core fetch pattern:**
```python
import comtradeapicall as comtrade

# US imports from China, 2023
df = comtrade.getTradeData(
    typeCode='C', freqCode='A', clCode='HS', period='2023',
    reporterCode='842', partnerCode='156', flowCode='M',
    subscription_key='YOUR_KEY')
```

### A.8 World Bank

| Attribute | Detail |
|---|---|
| **Provider** | World Bank Group |
| **URL** | https://data.worldbank.org |
| **Coverage** | 200+ countries, 1,600+ indicators |
| **Frequency** | Mostly annual |
| **Auth** | None |

**Core fetch pattern:**
```python
import wbgapi as wb

countries = ['USA','GBR','JPN','DEU','FRA','CAN','AUS','NZL','CHE','NOR','SWE','CHN','SGP']
df = wb.data.DataFrame('NY.GDP.PCAP.CD', countries, time=range(2010, 2025))
```

**Key indicator codes:** `NY.GDP.MKTP.CD` (GDP current USD), `NY.GDP.MKTP.KD.ZG` (GDP growth), `FP.CPI.TOTL.ZG` (inflation), `SL.UEM.TOTL.ZS` (unemployment), `BN.CAB.XOKA.GD.ZS` (current account % GDP), `GC.DOD.TOTL.GD.ZS` (gov debt % GDP), `BX.KLT.DINV.WD.GD.ZS` (FDI % GDP), `NE.TRD.GNFS.ZS` (trade % GDP).

### A.9 Nasdaq Data Link

| Attribute | Detail |
|---|---|
| **Provider** | Nasdaq (formerly Quandl) |
| **Coverage** | FRED mirror + some free macro datasets |
| **Rate Limit** | 50,000 requests/day (with key) |
| **Auth** | API key required |

**Core fetch pattern:**
```python
import nasdaqdatalink as ndl
ndl.ApiConfig.api_key = 'YOUR_KEY'

# FRED mirror access
gdp = ndl.get('FRED/GDP')
cpi = ndl.get('FRED/CPIAUCSL')
```

**Note:** Free datasets are mostly FRED mirrors. Primary value is as a fallback/alternative access method when FRED is rate-limited.

---

## Appendix B: Complete Series ID Registry

All provider-specific series IDs consolidated from the 9 data sources, organized by category.

### FRED Series IDs (US)

| Category | Series ID | Name | Frequency |
|---|---|---|---|
| **GDP** | `GDP` | Gross Domestic Product | Quarterly |
| | `GDPC1` | Real GDP | Quarterly |
| | `A191RL1Q225SBEA` | Real GDP Growth Rate | Quarterly |
| **Inflation** | `CPIAUCSL` | CPI (All Urban, SA) | Monthly |
| | `CPILFESL` | Core CPI (ex Food & Energy) | Monthly |
| | `PCEPI` | PCE Price Index | Monthly |
| | `PCEPILFE` | Core PCE | Monthly |
| | `PPIFIS` | PPI (Final Demand) | Monthly |
| **Employment** | `PAYEMS` | Nonfarm Payrolls (Total) | Monthly |
| | `UNRATE` | Unemployment Rate | Monthly |
| | `ICSA` | Initial Jobless Claims | Weekly |
| | `CCSA` | Continuing Claims | Weekly |
| | `AWHAETP` | Avg Weekly Hours (Private) | Monthly |
| | `CES0500000003` | Avg Hourly Earnings (Private) | Monthly |
| | `JTSJOL` | Job Openings (JOLTS) | Monthly |
| | `MANEMP` | Manufacturing Employment | Monthly |
| **Consumer** | `RSAFS` | Retail Sales (Total) | Monthly |
| | `UMCSENT` | Michigan Consumer Sentiment | Monthly |
| | `CSCICP03USM665S` | Consumer Confidence (CB) | Monthly |
| | `PCE` | Personal Consumption Expenditure | Monthly |
| **Manufacturing** | `INDPRO` | Industrial Production Index | Monthly |
| | `TCU` | Capacity Utilization | Monthly |
| | `DGORDER` | Durable Goods Orders | Monthly |
| | `NEWORDER` | Manufacturers New Orders | Monthly |
| **Housing** | `HOUST` | Housing Starts | Monthly |
| | `PERMIT` | Building Permits | Monthly |
| | `CSUSHPISA` | Case-Shiller Home Price Index | Monthly |
| | `EXHOSLUSM495S` | Existing Home Sales | Monthly |
| | `NHSUSSPT` | New Home Sales | Monthly |
| **Interest Rates** | `FEDFUNDS` | Fed Funds Rate (Effective) | Monthly |
| | `DFF` | Fed Funds Rate (Daily) | Daily |
| | `DGS2` | 2-Year Treasury | Daily |
| | `DGS10` | 10-Year Treasury | Daily |
| | `DGS30` | 30-Year Treasury | Daily |
| | `T10Y2Y` | 10Y-2Y Spread (Yield Curve) | Daily |
| | `T10Y3M` | 10Y-3M Spread | Daily |
| | `BAMLH0A0HYM2` | US High Yield OAS | Daily |
| **Money Supply** | `M2SL` | M2 Money Supply | Monthly |
| | `BOGMBASE` | Monetary Base | Monthly |
| | `WALCL` | Fed Total Assets | Weekly |
| **Trade** | `BOPGSTB` | Trade Balance (Goods & Services) | Monthly |
| | `NETEXP` | Net Exports | Quarterly |
| **Financial** | `SP500` | S&P 500 | Daily |
| | `VIXCLS` | VIX (CBOE Volatility Index) | Daily |
| | `DTWEXBGS` | Trade-Weighted USD Index (Broad) | Daily |
| | `DCOILWTICO` | WTI Crude Oil | Daily |
| | `GOLDAMGBD228NLBM` | Gold Price (London Fix) | Daily |

### IMF IFS Indicator Codes (International)

| Indicator | IFS Code | Frequency | Description |
|---|---|---|---|
| CPI | `PCPI_IX` | Monthly | Consumer Price Index |
| CPI (% YoY) | `PCPI_PC_CP_A_PT` | Monthly | CPI Year-over-Year |
| PPI | `PPPI_IX` | Monthly | Producer Price Index |
| GDP (nominal) | `NGDP` | Quarterly | Nominal GDP |
| GDP (real) | `NGDP_R` | Quarterly | Real GDP |
| Industrial Production | `AIP_IX` | Monthly | Industrial Production Index |
| Unemployment | `LUR_PT` | Monthly/Q | Unemployment Rate |
| Policy Rate | `FPOLM_PA` | Monthly | Monetary Policy Rate |
| Deposit Rate | `FIDR_PA` | Monthly | Deposit Rate |
| Lending Rate | `FILR_PA` | Monthly | Lending Rate |
| Exchange Rate (EoP) | `ENDA_XDC_USD_RATE` | Monthly | End-of-period per USD |
| Exchange Rate (avg) | `EDNA_XDC_USD_RATE` | Monthly | Period average per USD |
| Current Account | `BCA` | Quarterly | Current Account Balance |
| Trade Balance | `BTG` | Monthly | Balance on Goods |
| Reserves | `RAFA` | Monthly | Foreign Reserves |
| Broad Money (M2) | `FMB_XDC` | Monthly | Broad Money |
| Gov Debt (% GDP) | `GGXWDG_GDP_PT` | Annual | Government Debt to GDP |

### IMF WEO Codes (Annual Forecasts)

| Indicator | WEO Code | Description |
|---|---|---|
| Real GDP Growth | `NGDP_RPCH` | Annual GDP growth % |
| GDP (current USD) | `NGDPD` | Nominal GDP in USD billions |
| GDP per Capita | `NGDPDPC` | GDP per capita (current USD) |
| Inflation (avg) | `PCPIPCH` | Inflation rate, avg consumer prices |
| Inflation (end) | `PCPIEPCH` | Inflation rate, end of period |
| Unemployment | `LUR` | Unemployment rate |
| Current Account (% GDP) | `BCA_NGDPD` | Current account balance % GDP |
| Gov Balance (% GDP) | `GGXCNL_NGDP` | General gov net lending % GDP |
| Gov Debt (% GDP) | `GGXWDG_NGDP` | General gov gross debt % GDP |
| Population | `LP` | Population (millions) |

### OECD Dataset Codes

| Dataset Code | Name | Key Indicators |
|---|---|---|
| `MEI_CLI` | Composite Leading Indicators | CLI, CCI, BCI |
| `MEI` | Main Economic Indicators | Industrial Production, Retail Trade, Construction |
| `QNA` | Quarterly National Accounts | GDP components |
| `PRICES_CPI` | Consumer Prices | CPI by category |
| `STLABOUR` | Short-term Labour | Employment, Hours, Earnings |
| `KEI` | Key Economic Indicators | Composite of all above |
| `SNA_TABLE1` | GDP by Expenditure | C, I, G, NX components |

### ECB SDW Dataset Keys

| Dataset | Key Pattern | Description |
|---|---|---|
| `EXR` | `D.{CCY}.EUR.SP00.A` | Daily EUR exchange rates |
| `FM` | `D.U2.EUR.4F.KR.MRR_FR.LEV` | Main Refinancing Rate |
| `BSI` | `M.U2.N.V.M30.X.1.U2.2300.Z01.E` | Euro Area M3 |
| `YC` | `B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y` | 10Y Euro Area Yield |

### World Bank Indicator Codes

| Code | Description |
|---|---|
| `NY.GDP.MKTP.CD` | GDP (current USD) |
| `NY.GDP.MKTP.KD.ZG` | GDP Growth (%) |
| `NY.GDP.PCAP.CD` | GDP per capita (current USD) |
| `FP.CPI.TOTL.ZG` | Inflation, CPI (%) |
| `SL.UEM.TOTL.ZS` | Unemployment (%) |
| `BN.CAB.XOKA.GD.ZS` | Current Account (% GDP) |
| `GC.DOD.TOTL.GD.ZS` | Gov Debt (% GDP) |
| `BX.KLT.DINV.WD.GD.ZS` | FDI (% GDP) |
| `NE.TRD.GNFS.ZS` | Trade (% GDP) |

---

## Appendix C: Country Code Reference

Cross-provider country code mapping for all focus countries.

| Country | ISO2 | ISO3 | IMF Code | OECD Code | yfinance FX | Comtrade Code |
|---|---|---|---|---|---|---|
| United States | US | USA | 111 | USA | — (base) | 842 |
| United Kingdom | GB | GBR | 112 | GBR | `GBPUSD=X` | 826 |
| Euro Area | U2 | EMU | 163 | EA20 | `EURUSD=X` | — |
| Germany | DE | DEU | 134 | DEU | — (EUR) | 276 |
| France | FR | FRA | 132 | FRA | — (EUR) | 250 |
| Japan | JP | JPN | 158 | JPN | `JPY=X` | 392 |
| Canada | CA | CAN | 156 | CAN | `CAD=X` | 124 |
| Australia | AU | AUS | 193 | AUS | `AUDUSD=X` | 036 |
| New Zealand | NZ | NZL | 196 | NZL | `NZDUSD=X` | 554 |
| Switzerland | CH | CHE | 146 | CHE | `CHF=X` | 756 |
| Norway | NO | NOR | 142 | NOR | `NOK=X` | 578 |
| Sweden | SE | SWE | 144 | SWE | `SEK=X` | 752 |
| China | CN | CHN | 924 | CHN | `CNY=X` | 156 |
| Singapore | SG | SGP | 576 | — | `SGD=X` | 702 |

---

## Appendix D: API Keys & Package Summary

### API Key Registration

| Source | Registration URL | Time | Required |
|---|---|---|---|
| FRED | https://fred.stlouisfed.org/docs/api/api_key.html | 2 min | Yes |
| Finnhub | https://finnhub.io/register | 2 min | Yes |
| UN Comtrade | https://comtradeplus.un.org | 2 min | Yes |
| Nasdaq Data Link | https://data.nasdaq.com/sign-up | 2 min | Optional |
| IMF | https://data.imf.org (beta portal) | 0 min | No |
| OECD | — | 0 min | No |
| ECB | — | 0 min | No |
| World Bank | — | 0 min | No |
| Yahoo Finance | — | 0 min | No |

### Python Packages

```bash
# Create virtual environment
python -m venv macro_env
source macro_env/bin/activate  # Linux/Mac

# Core provider packages (all free)
pip install fredapi          # FRED + ALFRED
pip install sdmx1            # IMF + OECD + ECB + Eurostat
pip install yfinance         # Market prices
pip install finnhub-python   # Economic calendar + news
pip install wbgapi           # World Bank
pip install comtradeapicall  # UN Comtrade
pip install nasdaqdatalink   # Nasdaq/Quandl (backup)

# Data & analysis
pip install pandas numpy scipy statsmodels scikit-learn
pip install matplotlib seaborn plotly

# Storage
pip install sqlalchemy pyarrow
```
