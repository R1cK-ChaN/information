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
Official Sources (BLS, Fed, NBS, PBOC, ...)
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
                 ▼
        Analyst Agent (grounded reasoning)
```

All three packages write to a single `output/` directory at the repo root. Each item is deduplicated by SHA-256 and indexed in `output/catalog.db` for fast cross-package queries.

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
