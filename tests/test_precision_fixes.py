"""
tests/test_precision_fixes.py - Regression guards for three precision defects.

1. Marginal ΔNWC / ΔRevenue must not be pinned to the ±50% clamp by one
   near-flat-revenue year (KO: ΔRev $0.9B vs ΔNWC $8.4B → raw ratio 9.6).
2. The cache schema version must be *enforced*, not merely written — otherwise a
   file written before a new dataclass field existed decodes into an object
   missing that field.
3. Non-operating instruments (ETF / crypto / index) must be identified from the
   provider's ``instrumentType`` and answered honestly instead of producing an
   empty DCF report.
"""
from __future__ import annotations

import pytest

from classification.classifier import BusinessClassifier
from data.models import FinancialStatement, MarketData, FinancialData
from forecasts.nwc_utils import marginal_nwc_ratio


def _stmt(period: str, revenue: float, dnwc: float) -> FinancialStatement:
    return FinancialStatement(period_end=period, revenue=revenue, change_in_nwc=dnwc)


class TestShapedProjectionMatchesForwardDcf:
    """The reverse-DCF solve surface must be the forward DCF's own surface.

    Before this, the reverse solve projected a flat CAGR / flat margin, so its
    "implied growth" answered a different question than "what growth does the
    DCF's own model require to justify today's price". These tests pin the
    equivalence: at the DCF's own base growth and margin the shaped projection
    must return the DCF enterprise value.
    """

    @pytest.mark.parametrize("fixture", ["aapl_data", "msft_data", "nvda_data", "xom_data"])
    def test_shaped_projection_reproduces_dcf_enterprise_value(self, fixture, request):
        from config import resolve_forecast_horizon
        from forecasts.fcf_projection import (
            dcf_path_inputs_from_data,
            dcf_projection_shape,
            project_enterprise_value_shaped,
        )
        from forecasts.nwc_utils import business_type_from_profile
        from models.dcf import DCFModel

        data = request.getfixturevalue(fixture)
        profile = BusinessClassifier().classify(data)

        dcf = DCFModel().run(data, profile)
        if not dcf.is_success():
            pytest.skip(f"DCF did not solve for {data.ticker}")

        horizon = resolve_forecast_horizon(business_type_from_profile(profile))
        path = dcf_path_inputs_from_data(data, profile, horizon)
        assert path is not None

        eff_cagr, shape_rev, margin_offsets, om_center = dcf_projection_shape(
            path.base_revenue, path.base_growth, path.base_margin, horizon
        )
        proj = project_enterprise_value_shaped(
            path.base_revenue, eff_cagr, om_center, path.tax_rate,
            path.da_ratio, path.capex_ratio, path.nwc_marginal_ratio,
            dcf.breakdown["wacc"], dcf.breakdown["terminal_growth"], horizon,
            growth_shape=shape_rev, margin_offsets=margin_offsets,
        )
        rel = abs(proj.enterprise_value - dcf.enterprise_value) / abs(dcf.enterprise_value)
        assert rel < 1e-9, (
            f"{data.ticker}: shaped projection EV {proj.enterprise_value:,.0f} != "
            f"DCF EV {dcf.enterprise_value:,.0f} (rel {rel:.3e})"
        )

    def test_implied_revenue_cagr_roundtrips_to_target_ev(self, aapl_data, aapl_profile):
        """Feeding the solved CAGR back must reproduce the market EV."""
        from models.reverse_dcf import ReverseDCFModel

        model = ReverseDCFModel()
        result = model.run(aapl_data, aapl_profile)
        implied = result.breakdown.get("implied_revenue_cagr")
        if implied is None:
            pytest.skip("no implied revenue CAGR (outside the sanctioned band)")

        target = result.breakdown["target_enterprise_value"]
        horizon = result.breakdown["implied_expectations"]["horizon"]
        ev = model._project_ev(
            aapl_data, aapl_profile, implied,
            result.breakdown["wacc"], result.breakdown["terminal_growth"], horizon,
        )
        rel = abs(ev - target) / abs(target)
        assert rel <= model.rcfg.implied_residual_tol * 1.5


class TestMarginalNwcRobustness:
    def test_near_flat_revenue_year_does_not_dominate(self):
        # KO-shaped history: revenue barely moves in the newest year while ΔNWC
        # is large, so the aggregate ratio explodes past the clamp. The estimate
        # must fall back to the bounded flow ratio instead of silently reporting
        # "50% of every incremental revenue dollar goes to WC".
        annuals = [
            _stmt("2025", 47.9e9, 7.21e9),
            _stmt("2024", 47.1e9, 6.23e9),
            _stmt("2023", 45.8e9, 0.85e9),
            _stmt("2022", 43.0e9, 0.60e9),
        ]
        ratio, method = marginal_nwc_ratio(annuals)
        assert method == "flow_fallback"
        # Mean annual flow ratio ≈ 14.9B / 183.8B ≈ 0.081, not the 0.5 clamp.
        assert 0.0 < ratio < 0.2

    def test_flat_year_is_skipped_entirely(self):
        annuals = [
            _stmt("2025", 100.0e9, 50.0e9),  # ΔRev = 0.1% → skipped
            _stmt("2024", 99.9e9, 2.0e9),
            _stmt("2023", 90.0e9, 1.8e9),
        ]
        ratio, method = marginal_nwc_ratio(annuals)
        # Only the 2024/2023 pair contributes: 2.0/9.9 ≈ 0.202.
        assert method == "aggregate"
        assert ratio == pytest.approx(2.0 / 9.9, rel=1e-6)

    def test_single_period_falls_back_to_level_ratio(self):
        ratio, method = marginal_nwc_ratio([_stmt("2025", 100.0e9, 3.0e9)])
        assert method == "level_fallback"
        assert ratio == pytest.approx(0.03)

    def test_aggregate_inside_band_is_used_directly(self):
        # ΔNWC grows roughly with revenue → a clean marginal rate, no fallback.
        annuals = [
            _stmt("2025", 130.0e9, 3.0e9),
            _stmt("2024", 120.0e9, 2.0e9),
            _stmt("2023", 110.0e9, 1.0e9),
        ]
        ratio, method = marginal_nwc_ratio(annuals)
        assert method == "aggregate"
        assert ratio == pytest.approx(5.0 / 20.0, rel=1e-6)

    def test_clamp_bounds_are_respected(self):
        annuals = [
            _stmt("2025", 200.0e9, 100.0e9),
            _stmt("2024", 100.0e9, 0.0),
        ]
        ratio, _ = marginal_nwc_ratio(annuals)
        assert -0.5 <= ratio <= 0.5


class TestReportedWorkingCapitalIsFetched:
    """ΔNWC must come from the reported cash-flow line, not a residual.

    ``infer_change_in_nwc`` recovers ΔNWC as NOPAT + D&A − capex − FCF, which
    absorbs deferred revenue, SBC and every other non-capex cash item. Against
    Yahoo's reported ``ChangeInWorkingCapital`` that residual was off by $36B
    for META and $20B for GOOGL — enough to flip the marginal ratio's sign.
    """

    def test_provider_requests_the_reported_wc_series(self):
        from data.providers import YahooFinanceProvider

        assert "ChangeInWorkingCapital" in YahooFinanceProvider._ANNUAL_TIMESERIES

    def test_reported_value_wins_over_residual_inference(self):
        from data.nwc_utils import resolve_change_in_nwc

        stmt = FinancialStatement(
            period_end="2025-12-31",
            revenue=100.0,
            operating_income=30.0,
            depreciation_amortization=5.0,
            capex=-4.0,
            free_cash_flow=20.0,
            income_tax=6.0,
            change_in_nwc=2.5,  # reported line
        )
        # The residual would be 30*(1-0.2) + 5 - 4 - 20 = 5.0.
        assert resolve_change_in_nwc(stmt) == pytest.approx(2.5)

    def test_residual_is_used_only_when_the_line_is_absent(self):
        from data.nwc_utils import resolve_change_in_nwc

        stmt = FinancialStatement(
            period_end="2025-12-31",
            revenue=100.0,
            operating_income=30.0,
            depreciation_amortization=5.0,
            capex=-4.0,
            free_cash_flow=20.0,
            income_tax=6.0,
        )
        assert resolve_change_in_nwc(stmt) == pytest.approx(5.0)


class TestTtmCarriesSbcAndWorkingCapital:
    """TTM must sum SBC and ΔNWC, not drop them.

    ``compute_ttm_from_quarters`` rebuilt the TTM from revenue/earnings fields
    only, so ``ttm.stock_based_compensation`` was always ``None``. That made the
    whole SBC-normalization layer a silent no-op (GOOGL: $25B/yr never charged).
    """

    @staticmethod
    def _q(period_end: str, sbc: float, nwc: float, revenue: float = 100.0):
        return FinancialStatement(
            period_end=period_end,
            period_type="quarterly",
            revenue=revenue,
            operating_income=revenue * 0.25,
            depreciation_amortization=revenue * 0.05,
            capex=-revenue * 0.04,
            operating_cash_flow=revenue * 0.20,
            free_cash_flow=revenue * 0.16,
            change_in_nwc=nwc,
            stock_based_compensation=sbc,
            income_tax=revenue * 0.05,
            shares_outstanding=1_000.0,
        )

    def test_sbc_is_summed_across_four_quarters(self):
        from data.normalizer import FinancialNormalizer

        quarters = [
            self._q("2026-09-30", 8.0, 3.0),
            self._q("2026-06-30", 7.0, 2.0),
            self._q("2026-03-31", 6.0, 1.0),
            self._q("2025-12-31", 5.0, -4.0),
            self._q("2025-09-30", 99.0, 99.0),  # outside the TTM window
        ]
        ttm = FinancialNormalizer.compute_ttm_from_quarters(quarters)
        assert ttm is not None
        assert ttm.stock_based_compensation == pytest.approx(26.0)
        assert ttm.change_in_nwc == pytest.approx(2.0)

    def test_missing_sbc_stays_none_not_zero(self):
        from data.normalizer import FinancialNormalizer

        quarters = [
            FinancialStatement(period_end=f"2026-0{i}-30", period_type="quarterly",
                               revenue=100.0, free_cash_flow=16.0)
            for i in (9, 6, 3)
        ] + [FinancialStatement(period_end="2025-12-31", period_type="quarterly",
                                revenue=100.0, free_cash_flow=16.0)]
        ttm = FinancialNormalizer.compute_ttm_from_quarters(quarters)
        # A missing SBC line must not be fabricated as a zero cost.
        assert ttm.stock_based_compensation is None

    def test_provider_requests_quarterly_sbc_and_wc(self):
        from data.providers import YahooFinanceProvider

        q = YahooFinanceProvider._QUARTERLY_TIMESERIES
        assert "StockBasedCompensation" in q
        assert "ChangeInWorkingCapital" in q


class TestCacheSchemaVersionEnforced:
    def test_schema_mismatch_is_rejected(self, tmp_path, monkeypatch):
        from data.providers import YahooFinanceProvider

        provider = YahooFinanceProvider()
        monkeypatch.setattr(provider, "_cache_dir", str(tmp_path))
        monkeypatch.setattr(provider, "cache_enabled", True)

        path = provider._cache_path("AAPL")
        assert path is not None
        with open(path, "w", encoding="utf-8") as f:
            f.write('{"__cache_schema_version__": 0, "payload": {}}')

        assert provider._cache_read("AAPL") is None

    def test_matching_schema_is_accepted(self, tmp_path, monkeypatch):
        from data.providers import YahooFinanceProvider

        provider = YahooFinanceProvider()
        monkeypatch.setattr(provider, "_cache_dir", str(tmp_path))
        monkeypatch.setattr(provider, "cache_enabled", True)

        data = FinancialData(
            ticker="AAPL",
            market=MarketData(current_price=100.0, instrument_type="EQUITY"),
        )
        provider._cache_write("AAPL", data)
        restored = provider._cache_read("AAPL")
        assert restored is not None
        assert restored.market.instrument_type == "EQUITY"


class TestNonCompanyInstrumentDetection:
    @staticmethod
    def _data(ticker: str, instrument_type=None):
        return FinancialData(
            ticker=ticker,
            market=MarketData(current_price=100.0, instrument_type=instrument_type),
        )

    @pytest.mark.parametrize(
        "ticker,itype,expected_fragment",
        [
            ("SPY", "ETF", "ETF"),
            ("TLT", "ETF", "ETF"),
            ("BTC-USD", None, "加密货币"),
            ("ETH-USD", "CRYPTOCURRENCY", "加密货币"),
            ("^GSPC", None, "指数"),
            ("ES=F", None, "期货"),
            ("EURUSD=X", None, "外汇"),
        ],
    )
    def test_non_company_is_detected(self, ticker, itype, expected_fragment):
        from telegram_bot.telegram_bot import ValuationPipeline

        reason = ValuationPipeline._non_company_reason(self._data(ticker, itype))
        assert reason is not None
        assert expected_fragment in reason

    @pytest.mark.parametrize("ticker", ["AAPL", "NVDA", "BRK-B", "JPM", "BABA"])
    def test_operating_companies_are_not_flagged(self, ticker):
        from telegram_bot.telegram_bot import ValuationPipeline

        assert ValuationPipeline._non_company_reason(self._data(ticker, "EQUITY")) is None

    def test_pre_revenue_company_is_still_a_company(self):
        """Missing revenue is NOT a non-company signal."""
        from telegram_bot.telegram_bot import ValuationPipeline

        data = FinancialData(
            ticker="NBIS",
            market=MarketData(current_price=50.0, instrument_type="EQUITY"),
        )
        assert ValuationPipeline._non_company_reason(data) is None

    def test_report_states_the_model_premise_does_not_apply(self):
        from telegram_bot.telegram_bot import ValuationPipeline

        data = self._data("SPY", "ETF")
        reason = ValuationPipeline._non_company_reason(data)
        report = ValuationPipeline._non_company_report(data, reason)
        assert "不是经营性企业" in report
        assert "模型前提不成立" in report
        assert "SPY" in report
