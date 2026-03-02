"""Feed registry: FeedInfo dataclass + macro-finance feed definitions."""

from dataclasses import dataclass


@dataclass(frozen=True)
class FeedInfo:
    name: str
    url: str
    category: str


def _gnews(query: str, when: str = "1d") -> str:
    """Build a Google News RSS search URL."""
    return f"https://news.google.com/rss/search?q={query}+when:{when}&hl=en-US&gl=US&ceid=US:en"


# ── Feed definitions ──────────────────────────────────────────

FEEDS: list[FeedInfo] = [
    # ── markets (10) ──────────────────────────────────────────
    FeedInfo("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html", "markets"),
    FeedInfo("MarketWatch", _gnews("site:marketwatch.com+markets", "1d"), "markets"),
    FeedInfo("Yahoo Finance", "https://finance.yahoo.com/rss/topstories", "markets"),
    FeedInfo("Seeking Alpha", "https://seekingalpha.com/market_currents.xml", "markets"),
    FeedInfo("Reuters Markets", _gnews("site:reuters.com+markets+stocks", "1d"), "markets"),
    FeedInfo("Bloomberg Markets", _gnews("site:bloomberg.com+markets", "1d"), "markets"),
    FeedInfo("Investing.com News", _gnews("site:investing.com+markets", "1d"), "markets"),
    FeedInfo("WSJ Markets", "https://feeds.content.dowjones.io/public/rss/RSSMarketsMain", "markets"),
    FeedInfo("BBC Business", "https://feeds.bbci.co.uk/news/business/rss.xml", "markets"),
    FeedInfo("Nikkei Asia", "https://asia.nikkei.com/rss/feed/nar", "markets"),

    # ── forex (3) ─────────────────────────────────────────────
    FeedInfo("Forex News", _gnews('("forex"+OR+"currency"+OR+"FX+market")+trading', "1d"), "forex"),
    FeedInfo("Dollar Watch", _gnews('("dollar+index"+OR+DXY+OR+"US+dollar"+forex+OR+"euro+dollar"+trading)', "2d"), "forex"),
    FeedInfo("Central Bank Rates", _gnews('("central+bank"+rate+OR+"Fed+rate"+OR+"interest+rate+decision"+OR+"monetary+policy")+-crypto+-bitcoin', "2d"), "forex"),

    # ── bonds (3) ─────────────────────────────────────────────
    FeedInfo("Bond Market", _gnews('("bond+market"+OR+"treasury+yields"+OR+"bond+yields"+OR+"10-year+yield"+OR+"fixed+income")+-site:vietnambiz.vn+-site:vietstock.vn', "2d"), "bonds"),
    FeedInfo("Treasury Watch", _gnews('("US+Treasury"+OR+"Treasury+auction"+OR+"10-year+yield"+OR+"2-year+yield")', "2d"), "bonds"),
    FeedInfo("Corporate Bonds", _gnews('("corporate+bond"+OR+"high+yield+bond"+OR+"high+yield+debt"+OR+"investment+grade+bond"+OR+"credit+spread")', "3d"), "bonds"),

    # ── commodities (4) ───────────────────────────────────────
    FeedInfo("Oil & Gas", _gnews("(oil+price+OR+OPEC+OR+%22natural+gas%22+OR+%22crude+oil%22+OR+WTI+OR+Brent)", "1d"), "commodities"),
    FeedInfo("Gold & Metals", _gnews('("gold+price"+OR+"silver+price"+OR+"copper+futures"+OR+"platinum+futures"+OR+"precious+metals")+-site:meyka.com', "2d"), "commodities"),
    FeedInfo("Agriculture", _gnews("(wheat+OR+corn+OR+soybeans+OR+coffee+OR+sugar)+price+OR+commodity", "3d"), "commodities"),
    FeedInfo("Commodity Trading", _gnews('("commodity+trading"+OR+"futures+market"+OR+CME+OR+NYMEX+OR+COMEX)', "2d"), "commodities"),

    # ── crypto (5) ────────────────────────────────────────────
    FeedInfo("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/", "crypto"),
    FeedInfo("Cointelegraph", "https://cointelegraph.com/rss", "crypto"),
    FeedInfo("The Block", _gnews("site:theblock.co", "1d"), "crypto"),
    FeedInfo("Crypto News", _gnews('(bitcoin+OR+ethereum+OR+crypto+OR+"digital+assets")', "1d"), "crypto"),
    FeedInfo("DeFi News", _gnews('(DeFi+OR+"decentralized+finance"+OR+DEX+OR+"yield+farming")', "3d"), "crypto"),

    # ── centralbanks (8) ──────────────────────────────────────
    FeedInfo("Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml", "centralbanks"),
    FeedInfo("ECB Press", "https://www.ecb.europa.eu/rss/press.html", "centralbanks"),
    FeedInfo("ECB Watch", _gnews('("European+Central+Bank"+OR+ECB+OR+Lagarde)+(rate+OR+euro+OR+inflation+OR+"monetary+policy")+-crypto+-bitcoin', "3d"), "centralbanks"),
    FeedInfo("BoE Official", "https://www.bankofengland.co.uk/rss/news", "centralbanks"),
    FeedInfo("BoJ Watch", _gnews('("Bank+of+Japan"+OR+BoJ)+(rate+OR+yen+OR+yield+OR+"monetary+policy")+-crypto+-bitcoin', "3d"), "centralbanks"),
    FeedInfo("BoE Watch", _gnews('("Bank+of+England"+OR+BoE)+(rate+OR+sterling+OR+inflation+OR+"monetary+policy")+-crypto+-bitcoin', "3d"), "centralbanks"),
    FeedInfo("PBoC Watch", _gnews('("People%27s+Bank+of+China"+OR+PBoC+OR+PBOC)', "7d"), "centralbanks"),
    FeedInfo("Global Central Banks", _gnews('("rate+hike"+OR+"rate+cut"+OR+"interest+rate+decision")+central+bank', "3d"), "centralbanks"),

    # ── economic (5) ──────────────────────────────────────────
    FeedInfo("WSJ Economy", "https://feeds.content.dowjones.io/public/rss/socialeconomyfeed", "economic"),
    FeedInfo("IMF News", "https://www.imf.org/en/news/rss", "economic"),
    FeedInfo("Economic Data", _gnews('(CPI+OR+inflation+OR+GDP+OR+"jobs+report"+OR+"nonfarm+payrolls"+OR+PMI)', "2d"), "economic"),
    FeedInfo("Trade & Tariffs", _gnews('(tariff+OR+"trade+war"+OR+"trade+deficit"+OR+sanctions)', "2d"), "economic"),
    FeedInfo("Housing Market", _gnews('("housing+market"+OR+"home+prices"+OR+"mortgage+rates"+OR+REIT)', "3d"), "economic"),

    # ── ipo (3) ───────────────────────────────────────────────
    FeedInfo("IPO News", _gnews('(IPO+OR+"initial+public+offering"+OR+SPAC+OR+"direct+listing")', "3d"), "ipo"),
    FeedInfo("Earnings Reports", _gnews('("earnings+report"+OR+"quarterly+earnings"+OR+"earnings+beat"+OR+"earnings+surprise"+OR+"earnings+miss")+-site:defenseworld.net+-site:simplywall.st', "2d"), "ipo"),
    FeedInfo("M&A News", _gnews('("merger"+OR+"acquisition"+OR+"takeover+bid"+OR+"buyout")+billion', "3d"), "ipo"),

    # ── derivatives (2) ───────────────────────────────────────
    FeedInfo("Options Market", _gnews('(VIX+OR+"equity+options"+OR+"options+expiration"+OR+"options+market"+OR+"put+call+ratio")+-site:vietnambiz.vn', "2d"), "derivatives"),
    FeedInfo("Futures Trading", _gnews('("futures+trading"+OR+"S%26P+500+futures"+OR+"Nasdaq+futures")', "1d"), "derivatives"),

    # ── fintech (3) ───────────────────────────────────────────
    FeedInfo("Fintech News", _gnews('(fintech+OR+"payment+technology"+OR+"neobank"+OR+"digital+banking")', "3d"), "fintech"),
    FeedInfo("Trading Tech", _gnews('("algorithmic+trading"+OR+"trading+platform"+OR+"quantitative+finance")', "7d"), "fintech"),
    FeedInfo("Blockchain Finance", _gnews('("blockchain+finance"+OR+"tokenization"+OR+"digital+securities"+OR+CBDC)', "7d"), "fintech"),

    # ── regulation (5) ────────────────────────────────────────
    FeedInfo("SEC", "https://www.sec.gov/news/pressreleases.rss", "regulation"),
    FeedInfo("BIS", "https://www.bis.org/doclist/all_pressrels.rss", "regulation"),
    FeedInfo("Financial Regulation", _gnews("(SEC+OR+CFTC+OR+FINRA+OR+FCA)+regulation+OR+enforcement", "3d"), "regulation"),
    FeedInfo("Banking Rules", _gnews('("Basel+III"+OR+"Basel+IV"+OR+"Basel+regulation"+OR+"Basel+accord"+OR+"capital+requirements"+bank+OR+"banking+regulation")', "7d"), "regulation"),
    FeedInfo("Crypto Regulation", _gnews('(crypto+regulation+OR+"digital+asset"+regulation+OR+"stablecoin"+regulation)', "7d"), "regulation"),

    # ── institutional (3) ─────────────────────────────────────
    FeedInfo("Hedge Fund News", _gnews('("hedge+fund"+OR+"Bridgewater+Associates"+OR+"Citadel+LLC"+OR+"Renaissance+Technologies"+OR+"Two+Sigma"+OR+"DE+Shaw")', "7d"), "institutional"),
    FeedInfo("Private Equity", _gnews('("private+equity"+OR+Blackstone+OR+KKR+OR+Apollo+OR+Carlyle)', "3d"), "institutional"),
    FeedInfo("Sovereign Wealth", _gnews('("sovereign+wealth+fund"+OR+"pension+fund"+OR+"institutional+investor")', "7d"), "institutional"),

    # ── analysis (4) ──────────────────────────────────────────
    FeedInfo("NBER Working Papers", "https://www.nber.org/rss/new.xml", "analysis"),
    FeedInfo("Market Outlook", _gnews('("stock+market+outlook"+OR+"Wall+Street+outlook"+OR+"stock+market+forecast"+OR+"bull+market"+OR+"bear+market")+-site:openpr.com', "3d"), "analysis"),
    FeedInfo("Risk & Volatility", _gnews('("S%26P+500"+volatility+OR+VIX+OR+CBOE+OR+"risk+off"+stocks+OR+"market+correction")+-site:marketsmojo.com', "3d"), "analysis"),
    FeedInfo("Bank Research", _gnews('("Goldman+Sachs"+OR+"JPMorgan"+OR+"Morgan+Stanley")+forecast+OR+outlook', "3d"), "analysis"),

    # ── china (12) ───────────────────────────────────────────
    FeedInfo("SCMP China Economy", "https://www.scmp.com/rss/318421/feed", "china"),
    FeedInfo("SCMP China", "https://www.scmp.com/rss/4/feed", "china"),
    FeedInfo("SCMP Business", "https://www.scmp.com/rss/92/feed", "china"),
    FeedInfo("Xinhua China", "http://www.xinhuanet.com/english/rss/chinarss.xml", "china"),
    FeedInfo("Xinhua Business", "http://www.xinhuanet.com/english/rss/businessrss.xml", "china"),
    FeedInfo("China Daily BizChina", "https://www.chinadaily.com.cn/rss/bizchina_rss.xml", "china"),
    FeedInfo("China Daily News", "https://www.chinadaily.com.cn/rss/china_rss.xml", "china"),
    FeedInfo("CGTN Business", "https://www.cgtn.com/subscribe/rss/section/business.xml", "china"),
    FeedInfo("China Trade Watch", _gnews('(China+trade+OR+"China+tariff"+OR+"US+China"+trade)', "2d"), "china"),
    FeedInfo("China Markets", _gnews('("Shanghai+composite"+OR+"Hang+Seng"+OR+"CSI+300"+OR+"A-shares"+OR+"H-shares")', "2d"), "china"),
    FeedInfo("China Tech", _gnews('(Alibaba+OR+Tencent+OR+BYD+OR+Huawei+OR+Xiaomi)+stock+OR+earnings+OR+regulation', "3d"), "china"),
    FeedInfo("China Policy", _gnews('("China+GDP"+OR+"China+PMI"+OR+"China+CPI"+OR+"China+stimulus"+OR+"NPC"+OR+"NDRC")', "3d"), "china"),

    # ── thinktanks (5) ────────────────────────────────────────
    FeedInfo("Foreign Policy", "https://foreignpolicy.com/feed/", "thinktanks"),
    FeedInfo("Atlantic Council", "https://www.atlanticcouncil.org/feed/", "thinktanks"),
    FeedInfo("AEI", "https://www.aei.org/feed/", "thinktanks"),
    FeedInfo("CSIS", _gnews("site:csis.org", "7d"), "thinktanks"),
    FeedInfo("War on the Rocks", "https://warontherocks.com/feed", "thinktanks"),

    # ── government (2) ────────────────────────────────────────
    FeedInfo("Federal Reserve (Gov)", "https://www.federalreserve.gov/feeds/press_all.xml", "government"),
    FeedInfo("SEC (Gov)", "https://www.sec.gov/news/pressreleases.rss", "government"),

    # ── wireservices (4) ────────────────────────────────────
    FeedInfo("AP News", _gnews("source:associated_press", "1d"), "wireservices"),
    FeedInfo("France24 World", "https://www.france24.com/en/rss", "wireservices"),
    FeedInfo("France24 Asia-Pacific", "https://www.france24.com/en/asia-pacific/rss", "wireservices"),
    FeedInfo("France24 Business", "https://www.france24.com/en/business/rss", "wireservices"),

    # ── global (7) ──────────────────────────────────────────
    FeedInfo("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml", "global"),
    FeedInfo("BBC Asia", "https://feeds.bbci.co.uk/news/world/asia/rss.xml", "global"),
    FeedInfo("CNA Asia", "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=6511", "global"),
    FeedInfo("CNA Business", "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=6936", "global"),
    FeedInfo("Economist Leaders", "https://www.economist.com/leaders/rss.xml", "global"),
    FeedInfo("Economist Finance", "https://www.economist.com/finance-and-economics/rss.xml", "global"),
    FeedInfo("Forbes Business", "https://www.forbes.com/business/feed", "global"),
]

# ── Category index ────────────────────────────────────────────

_BY_CATEGORY: dict[str, list[FeedInfo]] = {}
_BY_NAME: dict[str, FeedInfo] = {}

for _f in FEEDS:
    _BY_CATEGORY.setdefault(_f.category, []).append(_f)
    _BY_NAME[_f.name] = _f

CATEGORIES = sorted(_BY_CATEGORY.keys())


class Registry:
    """Queryable registry of news feed definitions."""

    def list_feeds(self, category: str | None = None) -> list[FeedInfo]:
        if category:
            return list(_BY_CATEGORY.get(category, []))
        return list(FEEDS)

    def get_feed(self, name: str) -> FeedInfo:
        if name not in _BY_NAME:
            raise KeyError(f"Unknown feed: {name}")
        return _BY_NAME[name]

    def list_categories(self) -> list[str]:
        return list(CATEGORIES)

    def feed_count(self) -> int:
        return len(FEEDS)
