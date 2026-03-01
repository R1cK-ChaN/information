"""Indicator registry: canonical names → provider series IDs and metadata."""

from dataclasses import dataclass


@dataclass(frozen=True)
class IndicatorInfo:
    canonical_name: str
    description: str
    category: str
    frequency: str  # "daily", "weekly", "monthly", "quarterly"
    fred_series_id: str | None
    ttl_hours: int
    alfred_tracked: bool


# TTL defaults by frequency
_TTL = {"daily": 24, "weekly": 168, "monthly": 24, "quarterly": 168, "annual": 720}

_INDICATORS: list[IndicatorInfo] = [
    # --- Output ---
    IndicatorInfo("GDP", "Gross Domestic Product (Nominal)", "output", "quarterly", "GDP", _TTL["quarterly"], True),
    IndicatorInfo("GDP_REAL", "Real Gross Domestic Product", "output", "quarterly", "GDPC1", _TTL["quarterly"], True),
    IndicatorInfo("GDP_GROWTH", "Real GDP Growth Rate (Annualized)", "output", "quarterly", "A191RL1Q225SBEA", _TTL["quarterly"], False),
    # --- Inflation ---
    IndicatorInfo("CPI", "Consumer Price Index (All Urban, SA)", "inflation", "monthly", "CPIAUCSL", _TTL["monthly"], True),
    IndicatorInfo("CORE_CPI", "Core CPI (Excluding Food & Energy)", "inflation", "monthly", "CPILFESL", _TTL["monthly"], True),
    IndicatorInfo("PCE", "Personal Consumption Expenditures Price Index", "inflation", "monthly", "PCEPI", _TTL["monthly"], True),
    IndicatorInfo("CORE_PCE", "Core PCE Price Index", "inflation", "monthly", "PCEPILFE", _TTL["monthly"], True),
    IndicatorInfo("PPI", "Producer Price Index (Final Demand)", "inflation", "monthly", "PPIFIS", _TTL["monthly"], True),
    # --- Employment ---
    IndicatorInfo("NFP", "Total Nonfarm Payrolls", "employment", "monthly", "PAYEMS", _TTL["monthly"], True),
    IndicatorInfo("UNEMPLOYMENT", "Unemployment Rate", "employment", "monthly", "UNRATE", _TTL["monthly"], True),
    IndicatorInfo("INITIAL_CLAIMS", "Initial Jobless Claims", "employment", "weekly", "ICSA", _TTL["weekly"], False),
    IndicatorInfo("CONTINUING_CLAIMS", "Continuing Jobless Claims", "employment", "weekly", "CCSA", _TTL["weekly"], False),
    IndicatorInfo("AVG_WEEKLY_HOURS", "Average Weekly Hours (Total Private)", "employment", "monthly", "AWHAETP", _TTL["monthly"], False),
    IndicatorInfo("AVG_HOURLY_EARNINGS", "Average Hourly Earnings (Total Private)", "employment", "monthly", "CES0500000003", _TTL["monthly"], False),
    IndicatorInfo("JOLTS", "Job Openings (JOLTS)", "employment", "monthly", "JTSJOL", _TTL["monthly"], True),
    IndicatorInfo("MFG_EMPLOYMENT", "Manufacturing Employment", "employment", "monthly", "MANEMP", _TTL["monthly"], False),
    # --- Consumer ---
    IndicatorInfo("RETAIL_SALES", "Retail Sales (Total)", "consumer", "monthly", "RSAFS", _TTL["monthly"], True),
    IndicatorInfo("CONSUMER_SENTIMENT", "U of Michigan Consumer Sentiment", "consumer", "monthly", "UMCSENT", _TTL["monthly"], True),
    IndicatorInfo("CONSUMER_CONFIDENCE", "OECD Consumer Confidence (US)", "consumer", "monthly", "CSCICP03USM665S", _TTL["monthly"], False),
    IndicatorInfo("PCE_SPENDING", "Personal Consumption Expenditures", "consumer", "monthly", "PCE", _TTL["monthly"], True),
    # --- Manufacturing ---
    IndicatorInfo("INDUSTRIAL_PROD", "Industrial Production Index", "manufacturing", "monthly", "INDPRO", _TTL["monthly"], True),
    IndicatorInfo("CAPACITY_UTIL", "Capacity Utilization (Total)", "manufacturing", "monthly", "TCU", _TTL["monthly"], False),
    IndicatorInfo("DURABLE_GOODS", "Durable Goods New Orders", "manufacturing", "monthly", "DGORDER", _TTL["monthly"], True),
    IndicatorInfo("MFG_NEW_ORDERS", "Manufacturers New Orders", "manufacturing", "monthly", "NEWORDER", _TTL["monthly"], False),
    # --- Housing ---
    IndicatorInfo("HOUSING_STARTS", "Housing Starts (Total)", "housing", "monthly", "HOUST", _TTL["monthly"], True),
    IndicatorInfo("BUILDING_PERMITS", "Building Permits (Total)", "housing", "monthly", "PERMIT", _TTL["monthly"], False),
    IndicatorInfo("HOME_PRICE_INDEX", "S&P/Case-Shiller Home Price Index", "housing", "monthly", "CSUSHPISA", _TTL["monthly"], False),
    IndicatorInfo("EXISTING_HOME_SALES", "Existing Home Sales", "housing", "monthly", "EXHOSLUSM495S", _TTL["monthly"], False),
    IndicatorInfo("NEW_HOME_SALES", "New Home Sales", "housing", "monthly", "NHSUSSPT", _TTL["monthly"], False),
    # --- Rates ---
    IndicatorInfo("POLICY_RATE", "Federal Funds Rate (Monthly)", "rates", "monthly", "FEDFUNDS", _TTL["monthly"], False),
    IndicatorInfo("POLICY_RATE_DAILY", "Federal Funds Rate (Daily)", "rates", "daily", "DFF", _TTL["daily"], False),
    IndicatorInfo("TREASURY_2Y", "2-Year Treasury Yield", "rates", "daily", "DGS2", _TTL["daily"], False),
    IndicatorInfo("TREASURY_10Y", "10-Year Treasury Yield", "rates", "daily", "DGS10", _TTL["daily"], False),
    IndicatorInfo("TREASURY_30Y", "30-Year Treasury Yield", "rates", "daily", "DGS30", _TTL["daily"], False),
    IndicatorInfo("YIELD_CURVE_10Y2Y", "10Y-2Y Treasury Spread", "rates", "daily", "T10Y2Y", _TTL["daily"], False),
    IndicatorInfo("YIELD_CURVE_10Y3M", "10Y-3M Treasury Spread", "rates", "daily", "T10Y3M", _TTL["daily"], False),
    IndicatorInfo("HY_SPREAD", "High Yield Corporate Bond Spread", "rates", "daily", "BAMLH0A0HYM2", _TTL["daily"], False),
    # --- Money ---
    IndicatorInfo("M2", "M2 Money Supply", "money", "monthly", "M2SL", _TTL["monthly"], False),
    IndicatorInfo("MONETARY_BASE", "Monetary Base", "money", "monthly", "BOGMBASE", _TTL["monthly"], False),
    IndicatorInfo("FED_BALANCE_SHEET", "Fed Total Assets", "money", "weekly", "WALCL", _TTL["weekly"], False),
    # --- Trade ---
    IndicatorInfo("TRADE_BALANCE", "Trade Balance (Goods & Services)", "trade", "monthly", "BOPGSTB", _TTL["monthly"], False),
    IndicatorInfo("NET_EXPORTS", "Net Exports of Goods & Services", "trade", "quarterly", "NETEXP", _TTL["quarterly"], False),
    # --- Financial ---
    IndicatorInfo("SP500", "S&P 500 Index", "financial", "daily", "SP500", _TTL["daily"], False),
    IndicatorInfo("VIX", "CBOE Volatility Index", "financial", "daily", "VIXCLS", _TTL["daily"], False),
    IndicatorInfo("USD_INDEX", "Trade-Weighted US Dollar Index (Broad)", "financial", "daily", "DTWEXBGS", _TTL["daily"], False),
    IndicatorInfo("OIL_WTI", "WTI Crude Oil Price", "financial", "daily", "DCOILWTICO", _TTL["daily"], False),
]

# Build lookup indexes
_BY_NAME: dict[str, IndicatorInfo] = {ind.canonical_name: ind for ind in _INDICATORS}
_BY_FRED_ID: dict[str, IndicatorInfo] = {
    ind.fred_series_id: ind for ind in _INDICATORS if ind.fred_series_id
}


class Registry:
    """Indicator registry mapping canonical names to provider series IDs."""

    def get_indicator(self, canonical_name: str) -> IndicatorInfo:
        """Look up an indicator by canonical name. Raises KeyError if not found."""
        try:
            return _BY_NAME[canonical_name]
        except KeyError:
            raise KeyError(
                f"Unknown indicator '{canonical_name}'. "
                f"Use list_indicators() to see available indicators."
            )

    def list_indicators(self, category: str | None = None) -> list[IndicatorInfo]:
        """List all indicators, optionally filtered by category."""
        if category is None:
            return list(_INDICATORS)
        return [ind for ind in _INDICATORS if ind.category == category]

    def get_fred_series_id(self, canonical_name: str) -> str:
        """Get the FRED series ID for a canonical indicator name."""
        info = self.get_indicator(canonical_name)
        if info.fred_series_id is None:
            raise ValueError(f"Indicator '{canonical_name}' has no FRED series ID")
        return info.fred_series_id

    def get_alfred_series(self) -> list[str]:
        """List FRED series IDs that need revision tracking via ALFRED."""
        return [ind.fred_series_id for ind in _INDICATORS if ind.alfred_tracked and ind.fred_series_id]

    def categories(self) -> list[str]:
        """List all unique categories."""
        seen = []
        for ind in _INDICATORS:
            if ind.category not in seen:
                seen.append(ind.category)
        return seen
