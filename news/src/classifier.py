"""Finance-focused keyword classifier for news headlines."""

from dataclasses import dataclass
import re


@dataclass
class Classification:
    impact_level: str    # critical, high, medium, low, info
    finance_category: str  # monetary_policy, inflation, employment, etc.
    confidence: float


# Keywords that require word-boundary matching (short, ambiguous words)
_SHORT_KEYWORDS = frozenset([
    "war", "ban", "ipo", "gdp", "cpi", "pmi", "vix", "oil", "fed",
])

# ── Keyword maps: keyword → finance_category ─────────────────

CRITICAL_KEYWORDS: dict[str, str] = {
    "bank failure": "rates",
    "bank collapse": "rates",
    "market crash": "rates",
    "flash crash": "rates",
    "currency crisis": "fx",
    "currency collapse": "fx",
    "debt default": "rates",
    "sovereign default": "rates",
    "emergency rate cut": "monetary_policy",
    "emergency rate hike": "monetary_policy",
    "bank run": "rates",
    "financial crisis": "rates",
    "liquidity crisis": "rates",
    "credit crisis": "rates",
    "systemic risk": "rates",
    "contagion": "rates",
    "depression": "employment",
}

HIGH_KEYWORDS: dict[str, str] = {
    "rate cut": "monetary_policy",
    "rate hike": "monetary_policy",
    "interest rate decision": "monetary_policy",
    "fomc": "monetary_policy",
    "federal reserve": "monetary_policy",
    "fed meeting": "monetary_policy",
    "quantitative easing": "monetary_policy",
    "quantitative tightening": "monetary_policy",
    "taper": "monetary_policy",
    "nonfarm payrolls": "employment",
    "jobs report": "employment",
    "unemployment rate": "employment",
    "cpi report": "inflation",
    "inflation rate": "inflation",
    "pce price": "inflation",
    "core inflation": "inflation",
    "gdp growth": "rates",
    "gdp report": "rates",
    "recession": "rates",
    "yield curve inversion": "rates",
    "inverted yield curve": "rates",
    "tariff": "trade",
    "trade war": "trade",
    "sanctions": "trade",
    "debt ceiling": "rates",
    "government shutdown": "rates",
    "market crash": "rates",
    "bear market": "rates",
    "correction": "rates",
}

MEDIUM_KEYWORDS: dict[str, str] = {
    "inflation": "inflation",
    "cpi": "inflation",
    "ppi": "inflation",
    "pce": "inflation",
    "deflation": "inflation",
    "stagflation": "inflation",
    "jobless claims": "employment",
    "unemployment": "employment",
    "labor market": "employment",
    "treasury yield": "rates",
    "bond yield": "rates",
    "10-year yield": "rates",
    "2-year yield": "rates",
    "yield spread": "rates",
    "credit spread": "rates",
    "oil price": "commodities",
    "crude oil": "commodities",
    "opec": "commodities",
    "gold price": "commodities",
    "bitcoin": "crypto",
    "ethereum": "crypto",
    "crypto": "crypto",
    "earnings report": "earnings",
    "quarterly earnings": "earnings",
    "revenue beat": "earnings",
    "earnings miss": "earnings",
    "ipo": "ipo",
    "spac": "ipo",
    "merger": "earnings",
    "acquisition": "earnings",
    "buyout": "earnings",
    "pmi": "rates",
    "gdp": "rates",
    "vix": "rates",
    "volatility": "rates",
    "fed": "monetary_policy",
    "ecb": "monetary_policy",
    "bank of japan": "monetary_policy",
    "bank of england": "monetary_policy",
    "pboc": "monetary_policy",
    "dollar index": "fx",
    "dxy": "fx",
    "forex": "fx",
    "exchange rate": "fx",
    "currency": "fx",
}

LOW_KEYWORDS: dict[str, str] = {
    "housing market": "general",
    "home prices": "general",
    "mortgage rate": "rates",
    "consumer confidence": "general",
    "retail sales": "general",
    "consumer spending": "general",
    "manufacturing": "general",
    "industrial production": "general",
    "hedge fund": "general",
    "private equity": "general",
    "sovereign wealth": "general",
    "fintech": "general",
    "neobank": "general",
    "digital banking": "general",
    "algorithmic trading": "general",
    "options trading": "general",
    "futures trading": "general",
    "commodity trading": "commodities",
    "trade deficit": "trade",
    "current account": "trade",
    "balance of payments": "trade",
    "regulation": "regulation",
    "sec": "regulation",
    "cftc": "regulation",
    "enforcement": "regulation",
    "compliance": "regulation",
    "stablecoin": "crypto",
    "defi": "crypto",
    "blockchain": "crypto",
    "tokenization": "crypto",
    "cbdc": "crypto",
    "geopolitical": "geopolitical_risk",
    "geopolitics": "geopolitical_risk",
    "war": "geopolitical_risk",
    "conflict": "geopolitical_risk",
    "military": "geopolitical_risk",
}

# Exclusions — if these appear, skip classification
_EXCLUSIONS = frozenset([
    "protein", "couples", "relationship", "dating", "diet", "fitness",
    "recipe", "cooking", "shopping", "fashion", "celebrity", "movie",
    "tv show", "sports", "game", "concert", "festival", "wedding",
    "vacation", "travel tips", "life hack", "self-care", "wellness",
])

# Precompile regexes
_regex_cache: dict[str, re.Pattern] = {}


def _get_regex(keyword: str) -> re.Pattern:
    if keyword not in _regex_cache:
        escaped = re.escape(keyword)
        if keyword in _SHORT_KEYWORDS:
            _regex_cache[keyword] = re.compile(rf"\b{escaped}\b", re.IGNORECASE)
        else:
            _regex_cache[keyword] = re.compile(escaped, re.IGNORECASE)
    return _regex_cache[keyword]


def _match_keywords(title_lower: str, keywords: dict[str, str]) -> tuple[str, str] | None:
    """Return (keyword, finance_category) if any keyword matches, else None."""
    for kw, cat in keywords.items():
        if _get_regex(kw).search(title_lower):
            return kw, cat
    return None


def _classify_text(text: str) -> Classification | None:
    """Run keyword tiers against a single text block.

    Returns Classification if any keyword matches, else None.
    """
    lower = text.lower()

    if any(ex in lower for ex in _EXCLUSIONS):
        return Classification("info", "general", 0.3)

    match = _match_keywords(lower, CRITICAL_KEYWORDS)
    if match:
        return Classification("critical", match[1], 0.9)

    match = _match_keywords(lower, HIGH_KEYWORDS)
    if match:
        return Classification("high", match[1], 0.8)

    match = _match_keywords(lower, MEDIUM_KEYWORDS)
    if match:
        return Classification("medium", match[1], 0.7)

    match = _match_keywords(lower, LOW_KEYWORDS)
    if match:
        return Classification("low", match[1], 0.6)

    return None


def classify(title: str, description: str = "") -> Classification:
    """Classify a news item by financial impact and category.

    Matches keywords against the title first; if no match is found
    and a description is provided, also checks the description.
    """
    result = _classify_text(title)
    if result:
        return result

    if description:
        result = _classify_text(description)
        if result:
            return result

    return Classification("info", "general", 0.3)
