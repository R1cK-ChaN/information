# NewsStream

Macro-finance news ingestion and querying module. Fetches free RSS feeds, classifies headlines by financial impact, deduplicates, and persists everything into SQLite for historical time-series analysis.

Companion to `macro_data_layer` — same patterns (single class, YAML config, SQLite backend).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Optional: create `.env` with `GROQ_API_KEY=xxx` for LLM headline summarization.

## Quick Start

```python
from src import NewsStream

ns = NewsStream()

# Fetch news from all feeds
ns.bootstrap()

# Or refresh a single category
ns.refresh("centralbanks")

# Query
ns.get_latest(n=20)
ns.get_latest(n=10, impact_level="critical")
ns.get_headlines("markets", n=20, start="2025-06-01")
ns.search("rate cut", limit=10)

# Daily article counts for time-series analysis
ns.get_counts(start="2025-01-01", category="centralbanks")

# Admin
ns.describe()          # module metadata + stats
ns.list_feeds("forex") # registered feeds
ns.get_feed_status()   # sync log per feed
ns.prune(days=90)      # explicit cleanup

# Optional LLM summarization (requires GROQ_API_KEY)
ns.summarize_latest(n=10)

ns.close()
```

## Feed Categories (56 feeds, 15 categories)

| Category | Feeds | Key Sources |
|----------|-------|-------------|
| markets | 7 | CNBC, MarketWatch, Yahoo Finance, Seeking Alpha, Reuters, Bloomberg, Investing.com |
| forex | 3 | Forex News, Dollar/DXY Watch, Central Bank Rates |
| bonds | 3 | Bond Market, Treasury Watch, Corporate Bonds |
| commodities | 4 | Oil & Gas, Gold & Metals, Agriculture, Commodity Trading |
| crypto | 5 | CoinDesk, Cointelegraph, The Block, Crypto News, DeFi |
| centralbanks | 6 | Federal Reserve, ECB, BoJ, BoE, PBoC, Global CB |
| economic | 3 | CPI/GDP/NFP Data, Trade & Tariffs, Housing |
| ipo | 3 | IPO News, Earnings Reports, M&A |
| derivatives | 2 | Options Market, Futures Trading |
| fintech | 3 | Fintech, Trading Tech, Blockchain Finance |
| regulation | 4 | SEC, Financial Regulation, Banking Rules, Crypto Reg |
| institutional | 3 | Hedge Funds, Private Equity, Sovereign Wealth |
| analysis | 3 | Market Outlook, Risk & Volatility, Bank Research |
| thinktanks | 5 | Foreign Policy, Atlantic Council, AEI, CSIS, War on the Rocks |
| government | 2 | Federal Reserve, SEC (official RSS) |

Direct RSS where available (Fed, SEC, CoinDesk, Cointelegraph, think tanks). Google News search proxy for the rest.

## Classifier

Headlines are classified into 4 impact levels with 13 finance categories:

| Level | Confidence | Examples |
|-------|-----------|----------|
| critical | 0.9 | bank failure, market crash, currency crisis, emergency rate cut |
| high | 0.8 | rate cut/hike, FOMC, nonfarm payrolls, CPI report, tariff, recession |
| medium | 0.7 | inflation, treasury yield, oil price, bitcoin, earnings, IPO |
| low | 0.6 | housing market, hedge fund, fintech, regulation, geopolitical |
| info | 0.3 | no financial keywords matched |

Finance categories: `monetary_policy`, `inflation`, `employment`, `trade`, `earnings`, `ipo`, `commodities`, `fx`, `rates`, `crypto`, `regulation`, `geopolitical_risk`, `general`

## Deduplication

Jaccard word-overlap similarity (ported from worldmonitor):
- Tokenize: lowercase, strip punctuation, remove stopwords, keep tokens >2 chars
- Similarity: `|intersection| / min(|a|, |b|)`
- Threshold: 0.6 (configurable)
- Seeded from last 24h of stored titles on each refresh

## SQLite Schema

Three tables:

- **news_items** — all articles (accumulates over time, never auto-pruned)
- **daily_counts** — materialized daily counts by category/impact for fast time-series queries
- **sync_log** — per-feed fetch tracking with cooldown on repeated failures

## Config

`config/news_stream.yaml` — SQLite path, RSS timeout, max items per feed, dedup threshold, polling intervals, Groq model settings.

## Tests

```bash
pytest tests/ -v
```

89 tests, no network required (RSS calls mocked with respx).

## API Reference

```
NewsStream(config_path=None)

# Retrieval
.get_latest(n=20, impact_level=None) -> list[dict]
.get_headlines(category, n=20, start=None, end=None) -> list[dict]
.search(query, limit=20, start=None, end=None) -> list[dict]
.get_counts(start=None, end=None, category=None) -> list[dict]

# Ingestion
.refresh(category=None) -> dict
.bootstrap() -> dict

# LLM (optional)
.summarize_latest(n=10) -> str | None

# Admin
.describe() -> dict
.list_feeds(category=None) -> list[dict]
.get_feed_status() -> list[dict]
.prune(days=90) -> int
.close()
```
