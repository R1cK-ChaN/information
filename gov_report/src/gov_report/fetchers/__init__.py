"""Fetcher factory."""

from __future__ import annotations

from gov_report.fetchers.base import BaseFetcher

# Lazy imports to avoid circular deps
_FETCHER_MAP: dict[str, str] = {
    # US sources
    "us_bls_cpi": "gov_report.fetchers.us_bls:BLSFetcher",
    "us_bls_ppi": "gov_report.fetchers.us_bls:BLSFetcher",
    "us_bls_nfp": "gov_report.fetchers.us_bls:BLSFetcher",
    "us_fed_fomc_statement": "gov_report.fetchers.us_fed:FedFetcher",
    "us_fed_fomc_minutes": "gov_report.fetchers.us_fed:FedFetcher",
    "us_fed_beigebook": "gov_report.fetchers.us_fed:FedFetcher",
    "us_fed_ip": "gov_report.fetchers.us_fed:FedFetcher",
    "us_bea_gdp": "gov_report.fetchers.us_bea:BEAFetcher",
    "us_bea_pce": "gov_report.fetchers.us_bea:BEAFetcher",
    "us_bea_trade": "gov_report.fetchers.us_bea:BEAFetcher",
    "us_ism_manufacturing": "gov_report.fetchers.us_ism:ISMFetcher",
    "us_ism_services": "gov_report.fetchers.us_ism:ISMFetcher",
    "us_census_retail": "gov_report.fetchers.us_census:CensusFetcher",
    "us_census_housing": "gov_report.fetchers.us_census:CensusFetcher",
    "us_umich_sentiment": "gov_report.fetchers.us_umich:UMichFetcher",
    # CN sources
    "cn_stats_cpi": "gov_report.fetchers.cn_nbs:NBSFetcher",
    "cn_stats_ppi": "gov_report.fetchers.cn_nbs:NBSFetcher",
    "cn_stats_gdp": "gov_report.fetchers.cn_nbs:NBSFetcher",
    "cn_stats_pmi": "gov_report.fetchers.cn_nbs:NBSFetcher",
    "cn_stats_industrial": "gov_report.fetchers.cn_nbs:NBSFetcher",
    "cn_stats_retail": "gov_report.fetchers.cn_nbs:NBSFetcher",
    "cn_stats_fai": "gov_report.fetchers.cn_nbs:NBSFetcher",
    "cn_pboc_monetary": "gov_report.fetchers.cn_pboc:PBOCFetcher",
    "cn_pboc_lpr": "gov_report.fetchers.cn_pboc:PBOCFetcher",
    "cn_pboc_mpr": "gov_report.fetchers.cn_pboc:PBOCFetcher",
    "cn_caixin_pmi": "gov_report.fetchers.cn_caixin:CaixinFetcher",
    "cn_customs_trade": "gov_report.fetchers.cn_customs:CustomsFetcher",
    "cn_safe_fx": "gov_report.fetchers.cn_safe:SAFEFetcher",
    "cn_scio_press": "gov_report.fetchers.cn_scio:SCIOFetcher",
}


def get_fetcher(source_id: str, settings) -> BaseFetcher:
    """Instantiate the appropriate fetcher for a source_id."""
    dotted = _FETCHER_MAP.get(source_id)
    if not dotted:
        raise ValueError(f"Unknown source_id: {source_id}")
    module_path, class_name = dotted.rsplit(":", 1)
    import importlib

    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    return cls(settings, source_id)
