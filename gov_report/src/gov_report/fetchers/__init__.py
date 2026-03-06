"""Fetcher factory."""

from __future__ import annotations

from gov_report.fetchers.base import BaseFetcher

# Lazy imports to avoid circular deps
_FETCHER_MAP: dict[str, str] = {
    # US sources
    "us_fed_speeches": "gov_report.fetchers.us_fed:FedFetcher",
    "us_fed_press_all": "gov_report.fetchers.us_fed:FedFetcher",
    "us_fed_testimony": "gov_report.fetchers.us_fed:FedFetcher",
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
    "us_treasury_tic": "gov_report.fetchers.us_treasury:TreasuryFetcher",
    "us_treasury_debt": "gov_report.fetchers.us_treasury:TreasuryFetcher",
    # EU sources
    "eu_ecb_statement": "gov_report.fetchers.eu_ecb:ECBFetcher",
    "eu_ecb_minutes": "gov_report.fetchers.eu_ecb:ECBFetcher",
    "eu_ecb_bulletin": "gov_report.fetchers.eu_ecb:ECBFetcher",
    "eu_eurostat_cpi": "gov_report.fetchers.eu_eurostat:EurostatFetcher",
    "eu_eurostat_gdp": "gov_report.fetchers.eu_eurostat:EurostatFetcher",
    "eu_eurostat_employment": "gov_report.fetchers.eu_eurostat:EurostatFetcher",
    # UK sources
    "uk_boe_rate": "gov_report.fetchers.uk_boe:BOEFetcher",
    "uk_boe_minutes": "gov_report.fetchers.uk_boe:BOEFetcher",
    "uk_boe_mpr": "gov_report.fetchers.uk_boe:BOEFetcher",
    "uk_ons_cpi": "gov_report.fetchers.uk_ons:ONSFetcher",
    "uk_ons_gdp": "gov_report.fetchers.uk_ons:ONSFetcher",
    "uk_ons_employment": "gov_report.fetchers.uk_ons:ONSFetcher",
    # Japan sources
    "jp_boj_statement": "gov_report.fetchers.jp_boj:BOJFetcher",
    "jp_boj_outlook": "gov_report.fetchers.jp_boj:BOJFetcher",
    "jp_boj_minutes": "gov_report.fetchers.jp_boj:BOJFetcher",
    "jp_cao_gdp": "gov_report.fetchers.jp_boj:BOJFetcher",
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
    "cn_mof_fiscal": "gov_report.fetchers.cn_mof:MOFFetcher",
    "cn_mof_bond": "gov_report.fetchers.cn_mof:MOFFetcher",
    # ECB RSS sources (speeches, working papers)
    "ecb_press": "gov_report.fetchers.eu_ecb:ECBFetcher",
    "ecb_speeches": "gov_report.fetchers.eu_ecb:ECBFetcher",
    "ecb_working_papers": "gov_report.fetchers.eu_ecb:ECBFetcher",
    # International institutions
    "intl_imf_weo": "gov_report.fetchers.intl_imf:IMFFetcher",
    "intl_imf_gfsr": "gov_report.fetchers.intl_imf:IMFFetcher",
    "intl_imf_press": "gov_report.fetchers.intl_imf:IMFFetcher",
    "intl_wb_gep": "gov_report.fetchers.intl_worldbank:WorldBankFetcher",
    "intl_wb_press": "gov_report.fetchers.intl_worldbank:WorldBankFetcher",
    "intl_bis_quarterly": "gov_report.fetchers.intl_bis:BISFetcher",
    "intl_bis_research": "gov_report.fetchers.intl_bis:BISFetcher",
    "intl_bis_speech": "gov_report.fetchers.intl_bis:BISFetcher",
    "intl_oecd_outlook": "gov_report.fetchers.intl_oecd:OECDFetcher",
    "intl_oecd_cli": "gov_report.fetchers.intl_oecd:OECDFetcher",
    "intl_oecd_press": "gov_report.fetchers.intl_oecd:OECDFetcher",
    # Other central banks
    "au_rba_statement": "gov_report.fetchers.other_cb:OtherCBFetcher",
    "au_rba_rate": "gov_report.fetchers.other_cb:OtherCBFetcher",
    "ca_boc_statement": "gov_report.fetchers.other_cb:OtherCBFetcher",
    "ca_boc_mpr": "gov_report.fetchers.other_cb:OtherCBFetcher",
    "ch_snb_statement": "gov_report.fetchers.other_cb:OtherCBFetcher",
    "se_riksbank_statement": "gov_report.fetchers.other_cb:OtherCBFetcher",
    "se_riksbank_mpr": "gov_report.fetchers.other_cb:OtherCBFetcher",
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
