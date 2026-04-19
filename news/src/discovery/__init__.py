"""Discovery helpers — ad-hoc web search + generic URL fetch.

Used during ingestion to chase a source that a newsletter or report
references (see issue #3 scope item 7).

NOT agent-callable from this repo. The information layer only uses these
functions from deterministic ingestion code paths — never as a tool an
agent can invoke at will.
"""

from .fetch import FetchResult, fetch_url
from .references import extract_urls
from .search import SearchResult, search

__all__ = [
    "FetchResult",
    "SearchResult",
    "extract_urls",
    "fetch_url",
    "search",
]
