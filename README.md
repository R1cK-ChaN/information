# Information Layer

Source of truth for macro analysis. This layer aggregates, parses, and structures real-world data from official sources — government agencies, central banks, and financial news outlets — so that downstream analyst agents work with verified facts rather than hallucinated content.

## Why This Exists

LLMs hallucinate. When an analyst agent needs to reason about CPI prints, FOMC decisions, or trade data, it must ground its analysis in actual source documents. This repo provides that grounding: every data point traces back to a fetched URL, a parsed PDF, or a structured time series — never fabricated.

## Packages

| Package | Purpose |
|---------|---------|
| **[data/macro_data_layer](data/macro_data_layer/)** | Structured macro time series. FRED indicators (GDP, CPI, unemployment, yields), NY Fed reference rates (SOFR / EFFR / OBFR), CME-equivalent FedWatch rate expectations, and a VIX regime classifier stored alongside each print. |
| **[doc_parser](doc_parser/)** | PDF/document parsing pipeline. Ingests broker research, policy reports, and other PDFs via OCR (TextIn), then runs LLM entity extraction to produce structured JSON with 17 standardized fields. |
| **[gov_report](gov_report/)** | Government report crawler. Fetches official economic releases from BLS, Fed, BEA, ISM, NBS, PBOC, and other US/CN agencies. Converts HTML to markdown, runs the same LLM extraction as doc_parser, stores results in identical JSON schema. |
| **[news](news/)** | Financial news stream. Aggregates headlines from RSS + Telegram + IMAP newsletters, classifies by topic/impact, deduplicates via Jaccard similarity, tags each item against the shared subject vocabulary, and serves FTS5 + subject-scoped queries at `GET /items`. Also exposes an ad-hoc `discovery` helper (Brave search + httpx fetch with paywall fallback) for chasing referenced sources during ingestion. |
| **[notes](notes/)** | Research-notes artifact store. Drop frontmatter-tagged markdown files into an input folder; the CLI ingests them into the catalog under `source='notes'`, exports sha-named copies to `6_information_layer/notes/`, and indexes the body into the FTS search. |
| **[calendar](calendar/)** | Economic-calendar scraper (Investing.com). Stores upcoming releases with `indicator`, `country`, `importance`, `actual`, `forecast`, `previous` — surfaced alongside news/macro rows by the cross-source subject query. |
| **[widgets](widgets/)** | Shared utilities. Provides the `Catalog` SQLite index (plus FTS5 and subject tagging tables), the `SubjectTagger` that maps source-native identifiers to canonical `subject_id`s, and the YAML vocabulary loader. |

## Data Flow

```
Official Sources (BLS, Fed, NBS, PBOC, RSS feeds, Telegram, PDFs)
        │
        ▼
   ┌─────────┐     ┌────────────┐     ┌──────┐
   │gov_report│     │ doc_parser │     │ news │
   │ (crawl)  │     │  (parse)   │     │(feed)│
   └────┬─────┘     └─────┬──────┘     └──┬───┘
        │                 │               │
        ▼                 ▼               ▼
   Standardized JSON (17 entity fields + markdown)
        │                 │               │
        └────────┬────────┴───────────────┘
                 ▼
            output/
              ├── catalog.db        ← SQLite index (all fields + sha256 + json_path)
              └── <sha[:4]>/
                    └── <sha>.json  ← one JSON per document/article
                 │
                 ▼  export_information_layer.py
            6_information_layer/
              ├── news/<sha[:12]>.md       ← YAML frontmatter + markdown body
              └── gov_report/<sha[:12]>.md
                 │
                 ▼  POST /admin/collections/sync
            RAG Service (Milvus)
              └── kb_information collection  ← agents query from here
```

All packages write to a single `output/` directory. Each item is deduplicated by SHA-256
and indexed in `output/catalog.db`. The export script converts catalog items to markdown
files in `6_information_layer/` which the RAG service indexes into Milvus — agents never
touch the catalog directly.

## JSON Schema (shared by all packages)

Every extracted document produces a JSON with these entity fields:

`title`, `institution`, `authors`, `publish_date`, `data_period`, `country`, `market`, `asset_class`, `sector`, `document_type`, `event_type`, `subject`, `subject_id`, `language`, `contains_commentary`, `impact_level`, `confidence`

Plus full `markdown` content, `parse_info`, and `extraction_info`.

## Subject Tagging & Cross-Source Query

A single canonical vocabulary in [`config/subjects.yaml`](config/subjects.yaml) binds news, newsletters, gov reports, calendar events, notes, and macro series to the same `subject_id` (e.g. `econ.cpi`, `rate.us.sofr`, `rate.us.fedwatch`, `vol.vix`). Source-native identifiers — FRED series, NY Fed rate names, calendar `indicator` strings, and news title regex — resolve through alias tables at ingest time, so an agent asking for "CPI" gets the same subject regardless of which package wrote the row.

The catalog exposes two composable HTTP queries on the news API:

- `GET /items?subject=econ.cpi` — merged view across catalog + calendar + macro data, ranked by recency.
- `GET /items?q=<text>` — BM25 full-text search over `title + body` via SQLite FTS5, composable with `subject=` and the existing filters (`impact_level`, `market`, `institution`, ...).

Notes, FedWatch forward curves, and NY Fed rate snapshots all feed into these queries through their subject aliases — no per-source plumbing required.

## Quick Start

```bash
# Install shared widgets (required by all packages)
pip install -e .

# Install packages (each is a standalone Python package)
pip install -e ./doc_parser
pip install -e ./gov_report
pip install -e ./news
pip install -e ./data/macro_data_layer

# Fetch a US government report → JSON in output/ + catalog entry
gov-report fetch us_bls_cpi

# Fetch a CN government report
gov-report fetch cn_stats_cpi

# Parse a PDF document
doc-parser process /path/to/report.pdf

# Check fetch history
gov-report status

# Ingest research notes (drop *.md with frontmatter into 6_information_layer/notes_input/)
python -m notes.ingest

# Pull NY Fed reference rates (SOFR/EFFR/OBFR) + FedWatch forward curve
python -c "from src.data_layer import MacroDataLayer; dl=MacroDataLayer(); \
  dl.refresh_ny_fed_rates(); dl.refresh_fedwatch()"
```

---

## Deployment: News Feed (Continuous)

The `news/` package ships a `refresher.py` + `Dockerfile` that run the full pipeline
continuously as a single Docker service. See [news/README.md](news/README.md#deployment)
for full details.

```bash
# From information/
cp news/.env.example news/.env   # fill in RAG_API_KEY etc.
docker compose up -d --build
docker compose logs -f news-refresher
```

### What the refresher does every 15 min

| Step | Output |
|---|---|
| `news.refresh()` | `output/<sha>.json` + `output/catalog.db` |
| `export_information_layer.py` | `6_information_layer/news/<sha[:12]>.md` |
| `POST /admin/collections/sync` | Incremental Milvus index in RAG service |

Only runs export + sync when new items are stored — idle cycles produce no I/O.

### Shared volumes

```
information/
├── output/                  ← JSON files + catalog.db  (written by refresher)
└── 6_information_layer/
    ├── news/                ← .md files for RAG        (written by refresher, read by RAG)
    └── gov_report/          ← .md files for RAG        (written manually / future automation)
```

The RAG service mounts `6_information_layer/` read-only via `RAG_INFO_LAYER_PATH`
(set in `rag-service/docker-compose.yml`). No code changes are needed in the RAG service —
new `.md` files are picked up automatically on the next `/admin/collections/sync` call.
