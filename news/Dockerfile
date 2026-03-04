# Build context: workspace root (analyst/)
# This lets us reach both information/ and rag-service/ in a single build.
#
#   docker compose -f information/docker-compose.yml up --build

FROM python:3.12-slim

# ── system deps for readability-lxml (C extensions) ──────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libxml2-dev \
        libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

# ── install shared widgets (required by news-stream) ─────────────────────────
COPY information/widgets/ /app/information/widgets/
RUN pip install --no-cache-dir -e /app/information/widgets

# ── install news-stream ───────────────────────────────────────────────────────
COPY information/news/ /app/information/news/
RUN pip install --no-cache-dir -e /app/information/news

# ── copy the export script (called by refresher.py) ──────────────────────────
COPY rag-service/scripts/export_information_layer.py \
     /app/rag-service/scripts/export_information_layer.py

# ── create output dirs (overlaid by volume mounts at runtime) ────────────────
RUN mkdir -p \
    /app/information/output \
    /app/information/6_information_layer/news \
    /app/information/6_information_layer/gov_report \
    /app/information/news/data

# ── runtime env defaults (all overridable via docker-compose environment:) ───
ENV CATALOG_PATH=/app/information/output/catalog.db
ENV INFO_LAYER_PATH=/app/information/6_information_layer
ENV EXPORT_SCRIPT=/app/rag-service/scripts/export_information_layer.py
ENV REFRESH_INTERVAL_SECONDS=900
ENV RAG_SERVICE_URL=http://localhost:8000

WORKDIR /app/information/news

CMD ["python", "refresher.py"]
