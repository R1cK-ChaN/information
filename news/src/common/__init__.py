"""Common pipeline infrastructure (providers, classifier, dedup, export, sync)."""

from .base_provider import BaseProvider
from .classifier import classify, Classification
from .deduplicator import Deduplicator
from .export import convert_item, convert_item_llm, save_extraction, _news_sha256, _compose_markdown
from .summarizer import Summarizer
from .sync_store import SyncStore
