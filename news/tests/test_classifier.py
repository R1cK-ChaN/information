"""Tests for the finance keyword classifier."""

from src.common.classifier import classify


class TestCriticalLevel:
    def test_bank_failure(self):
        r = classify("Major bank failure rocks financial system")
        assert r.impact_level == "critical"
        assert r.confidence == 0.9

    def test_market_crash(self):
        r = classify("Global market crash wipes trillions")
        assert r.impact_level == "critical"

    def test_currency_crisis(self):
        r = classify("Currency crisis deepens in emerging markets")
        assert r.impact_level == "critical"
        assert r.finance_category == "fx"

    def test_emergency_rate_cut(self):
        r = classify("Fed announces emergency rate cut")
        assert r.impact_level == "critical"
        assert r.finance_category == "monetary_policy"

    def test_debt_default(self):
        r = classify("Sovereign debt default fears grow")
        assert r.impact_level == "critical"


class TestHighLevel:
    def test_rate_cut(self):
        r = classify("Fed signals rate cut at next meeting")
        assert r.impact_level == "high"
        assert r.finance_category == "monetary_policy"

    def test_fomc(self):
        r = classify("FOMC minutes reveal hawkish stance")
        assert r.impact_level == "high"
        assert r.finance_category == "monetary_policy"

    def test_nonfarm_payrolls(self):
        r = classify("Nonfarm payrolls beat expectations")
        assert r.impact_level == "high"
        assert r.finance_category == "employment"

    def test_cpi_report(self):
        r = classify("CPI report shows inflation cooling")
        assert r.impact_level == "high"
        assert r.finance_category == "inflation"

    def test_tariff(self):
        r = classify("New tariff on Chinese imports announced")
        assert r.impact_level == "high"
        assert r.finance_category == "trade"

    def test_recession(self):
        r = classify("Economists warn of looming recession")
        assert r.impact_level == "high"
        assert r.finance_category == "rates"

    def test_yield_curve_inversion(self):
        r = classify("Yield curve inversion deepens")
        assert r.impact_level == "high"


class TestMediumLevel:
    def test_inflation(self):
        r = classify("Inflation expectations remain elevated")
        assert r.impact_level == "medium"
        assert r.finance_category == "inflation"

    def test_oil_price(self):
        r = classify("Oil price surges on OPEC production cut")
        assert r.impact_level == "medium"
        assert r.finance_category == "commodities"

    def test_bitcoin(self):
        r = classify("Bitcoin hits new all-time high")
        assert r.impact_level == "medium"
        assert r.finance_category == "crypto"

    def test_earnings(self):
        r = classify("Apple earnings report beats estimates")
        assert r.impact_level == "medium"
        assert r.finance_category == "earnings"

    def test_ipo(self):
        r = classify("Stripe IPO valued at $70 billion")
        assert r.impact_level == "medium"
        assert r.finance_category == "ipo"

    def test_vix(self):
        r = classify("VIX spikes as uncertainty grows")
        assert r.impact_level == "medium"

    def test_gdp_short_keyword(self):
        r = classify("GDP shows strong growth")
        assert r.impact_level == "medium"
        # "gdp" is a short keyword, should match with word boundary
        assert r.finance_category == "rates"


class TestLowLevel:
    def test_housing(self):
        r = classify("Housing market shows signs of cooling")
        assert r.impact_level == "low"

    def test_hedge_fund(self):
        r = classify("Hedge fund manager discusses strategy")
        assert r.impact_level == "low"

    def test_fintech(self):
        r = classify("Fintech startup raises Series B")
        assert r.impact_level == "low"

    def test_regulation(self):
        r = classify("New financial regulation proposed")
        assert r.impact_level == "low"
        assert r.finance_category == "regulation"


class TestInfoLevel:
    def test_no_match(self):
        r = classify("New restaurant opens downtown")
        assert r.impact_level == "info"
        assert r.finance_category == "general"
        assert r.confidence == 0.3

    def test_exclusion(self):
        r = classify("Celebrity fashion trends influence shopping")
        assert r.impact_level == "info"
        assert r.confidence == 0.3


class TestEdgeCases:
    def test_case_insensitive(self):
        r = classify("FEDERAL RESERVE ANNOUNCES RATE CUT")
        assert r.impact_level == "high"

    def test_short_keyword_word_boundary(self):
        # "war" should not match inside "warranty"
        r = classify("Extended warranty program launched")
        assert r.impact_level == "info"

    def test_war_standalone(self):
        r = classify("Trade war escalates between nations")
        assert r.impact_level == "high"
        assert r.finance_category == "trade"
