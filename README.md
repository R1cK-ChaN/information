# Information Layer

Source of truth for macro analysis. This layer aggregates, parses, and structures real-world data from official sources — government agencies, central banks, and financial news outlets — so that downstream analyst agents work with verified facts rather than hallucinated content.

## Why This Exists

LLMs hallucinate. When an analyst agent needs to reason about CPI prints, FOMC decisions, or trade data, it must ground its analysis in actual source documents. This repo provides that grounding: every data point traces back to a fetched URL, a parsed PDF, or a structured time series — never fabricated.

## Packages

| Package | Purpose |
|---------|---------|
| **[data/macro_data_layer](data/macro_data_layer/)** | Structured macro time series (FRED, etc.). Provides clean numeric data for indicators like GDP, CPI, unemployment, yields. |
| **[doc_parser](doc_parser/)** | PDF/document parsing pipeline. Ingests broker research, policy reports, and other PDFs via OCR (TextIn), then runs LLM entity extraction to produce structured JSON with 17 standardized fields. |
| **[gov_report](gov_report/)** | Government report crawler. Fetches official economic releases from BLS, Fed, BEA, ISM, NBS, PBOC, and other US/CN agencies. Converts HTML to markdown, runs the same LLM extraction as doc_parser, stores results in identical JSON schema. |
| **[news](news/)** | Financial news stream. Aggregates headlines from RSS feeds, classifies by topic/impact, deduplicates via Jaccard similarity, and writes structured JSON inline during refresh. |
| **[widgets](widgets/)** | Shared utilities. Provides the `Catalog` SQLite index used by all packages for dedup and querying. |

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
