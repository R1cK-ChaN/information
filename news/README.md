# NewsStream

Macro-finance news ingestion and querying module. Fetches free RSS feeds, fetches full article content from source URLs, classifies headlines by financial impact, deduplicates, and persists everything into SQLite for historical time-series analysis.

Companion to `macro_data_layer` — same patterns (single class, YAML config, SQLite backend).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Optional: create `.env` with `GROQ_API_KEY=xxx` for LLM headline summarization, `LLM_API_KEY` for structured extraction.

### Paywall fetcher (optional)

For full article content from paywalled sites (Bloomberg, Reuters, WSJ, Economist, etc.):

```bash
pip install -e ".[playwright]"
python -m playwright install chromium
python -m src.paywall_login https://www.bloomberg.com   # log in, close browser to save session
```

Re-run the login command if a session expires. See [Paywall Fetcher](#paywall-fetcher) below.

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

## Feed Categories (88 feeds, 18 categories)

| Category | Feeds | Key Sources |
|----------|-------|-------------|
| markets | 10 | CNBC, MarketWatch, Yahoo Finance, Seeking Alpha, Reuters, Bloomberg, Investing.com, WSJ, BBC, Nikkei |
| forex | 3 | Forex News, Dollar/DXY Watch, Central Bank Rates |
| bonds | 3 | Bond Market, Treasury Watch, Corporate Bonds |
| commodities | 4 | Oil & Gas, Gold & Metals, Agriculture, Commodity Trading |
| crypto | 5 | CoinDesk, Cointelegraph, The Block, Crypto News, DeFi |
| centralbanks | 8 | Federal Reserve, ECB Press, ECB Watch, BoE Official, BoJ, BoE, PBoC, Global CB |
| economic | 5 | WSJ Economy, IMF, Economic Data, Trade & Tariffs, Housing |
| ipo | 3 | IPO News, Earnings Reports, M&A |
| derivatives | 2 | Options Market, Futures Trading |
| fintech | 3 | Fintech, Trading Tech, Blockchain Finance |
| regulation | 5 | SEC, BIS, Financial Regulation, Banking Rules, Crypto Reg |
| institutional | 3 | Hedge Funds, Private Equity, Sovereign Wealth |
| analysis | 4 | NBER, Market Outlook, Risk & Volatility, Bank Research |
| china | 12 | SCMP, Xinhua, China Daily, CGTN, China Trade/Markets/Tech/Policy |
| thinktanks | 5 | Foreign Policy, Atlantic Council, AEI, CSIS, War on the Rocks |
| government | 2 | Federal Reserve, SEC (official RSS) |
| wireservices | 4 | AP News, France24/AFP World, Asia-Pacific, Business |
| global | 7 | BBC World, BBC Asia, CNA Asia, CNA Business, Economist Leaders, Economist Finance, Forbes Business |

Direct RSS where available (Fed, ECB, BoE, SEC, BIS, IMF, WSJ, BBC, Nikkei, SCMP, Xinhua, China Daily, CGTN, CoinDesk, Cointelegraph, France24, CNA, Economist, Forbes, think tanks). Google News search proxy for the rest.

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

## Article Fetcher

After RSS fetch and dedup, the pipeline fetches full article HTML from each item's `link` URL and replaces the thin RSS description with extracted content:

```
Phase 1:   RSS fetch → dedup → pending_items[]
Phase 1.5: For each item: resolve URL → fetch article → readability + markdownify → enrich item["description"]
Phase 2:   classify / LLM extract → save JSON
```

- Uses `readability-lxml` to extract readable content and `markdownify` to convert to markdown
- Truncates at 15,000 chars (configurable via `providers.article_fetcher.max_content_chars`)
- **Google News proxy URLs** (`news.google.com/rss/articles/CBMi...`) are resolved to real article URLs via Google's batchexecute API (fetches article page for per-article signature/timestamp, then decodes)
- Graceful fallback to RSS description on any error (timeout, 403, parse failure) — never loses content
- Direct feeds (Fed, ECB, BoE, BIS) typically yield 800–15,000 chars; Google News proxy articles yield 1,000–6,000 chars after resolution

## Paywall Fetcher

Sites that return 403/401 to plain HTTP clients (bot protection, login walls) are routed through a headless Chromium browser with a persistent cookie profile:

```
ArticleFetcher.fetch_article(url)
  ├── resolve Google News proxy URL (httpx, unchanged)
  ├── domain in paywall_domains? → PaywallFetcher (Playwright headless Chromium)
  └── otherwise → httpx fetch (unchanged)
  └── on ANY failure → rss_description fallback
```

Configured domains (`config/news_stream.yaml` → `providers.paywall_fetcher.domains`):
bloomberg.com, reuters.com, barrons.com, nytimes.com, wsj.com, fxstreet.com, theblock.co, france24.com, economist.com, forbes.com

- Browser is lazily started on first paywall URL and stays alive for the refresh cycle
- Playwright is conditionally imported — never loaded if no paywall domains configured or package not installed
- Login sessions are saved in `data/browser_profile/` (git-ignored)
- One-time login: `python -m src.paywall_login <url>` opens a visible browser for manual login

## SQLite Schema

Three tables:

- **news_items** — all articles (accumulates over time, never auto-pruned)
- **daily_counts** — materialized daily counts by category/impact for fast time-series queries
- **sync_log** — per-feed fetch tracking with cooldown on repeated failures

## Config

`config/news_stream.yaml` — SQLite path, RSS timeout, max items per feed, article fetcher timeout/max chars, paywall fetcher domains/browser profile/timeout, dedup threshold, polling intervals, Groq model settings.

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

---

## Deployment

The `refresher.py` script runs the full pipeline continuously as a Docker service.
Agents do **not** query the catalog directly — they query the RAG service, which indexes
the markdown files produced by this pipeline.

### Full pipeline (every 15 min)

```
[130+ RSS / Telegram feeds]
        │
        ▼  refresh()
information/output/<sha[:4]>/<sha>.json    ← structured extraction per article
information/output/catalog.db             ← SQLite index (dedup + querying)
        │
        ▼  export_information_layer.py
information/6_information_layer/news/<sha[:12]>.md   ← YAML frontmatter + markdown
        │
        ▼  POST /admin/collections/sync
RAG service (Milvus)                      ← agents query from here
```

Export and RAG sync only fire when `stored > 0` — idle cycles are free.
RAG sync failures are non-fatal and retried on the next cycle.

### Docker setup

```bash
# 1. Copy and fill in keys
cp news/.env.example news/.env
# Edit news/.env — set RAG_API_KEY if your RAG service has auth on

# 2. Build and start (from information/)
docker compose up -d --build

# 3. Follow logs
docker compose logs -f news-refresher
```

Expected log output after the bootstrap run:

```
Bootstrap done — fetched=1300  stored=120  duplicates=0  errors=4
Export output: Export complete: 120 news, 0 gov_report, 0 skipped
RAG sync triggered: {"status": "ok", ...}
Sleeping 900s until next refresh...
```

### Environment variables (`news/.env`)

| Variable | Default | Description |
|---|---|---|
| `REFRESH_INTERVAL_SECONDS` | `900` | Polling interval in seconds (15 min) |
| `RAG_SERVICE_URL` | `http://host.docker.internal:8000` | RAG service sync endpoint base URL |
| `RAG_API_KEY` | _(empty)_ | `X-API-Key` header if RAG auth is enabled |
| `GROQ_API_KEY` | _(empty)_ | Groq key for optional headline summarization |
| `LLM_API_KEY` | _(empty)_ | LLM key for optional structured extraction |
| `LLM_BASE_URL` | `https://openrouter.ai/api/v1` | LLM provider base URL |
| `LLM_MODEL` | `openai/gpt-4o-mini` | Model for structured extraction |

`CATALOG_PATH`, `INFO_LAYER_PATH`, and `EXPORT_SCRIPT` are set automatically by
`docker-compose.yml` to match the volume mounts — do not override unless running outside Docker.

### Volume mounts

| Host path | Container path | Purpose |
|---|---|---|
| `information/output/` | `/app/information/output/` | JSON files + catalog.db |
| `information/6_information_layer/` | `/app/information/6_information_layer/` | Exported .md for RAG |
| `news_sync_data` (named) | `/app/information/news/data/` | Feed polling state (persisted) |

The `information/6_information_layer/` directory is mounted read-only by the RAG service
container (`rag-service/docker-compose.yml` → `RAG_INFO_LAYER_PATH`). Both services point
at the same host directory — the refresher writes, the RAG container reads.

### Running locally (no Docker)

```bash
cd information/news
pip install -e ../widgets -e .

# Optional: set env vars
export RAG_SERVICE_URL=http://localhost:8000
export RAG_API_KEY=your-key

python refresher.py
```
