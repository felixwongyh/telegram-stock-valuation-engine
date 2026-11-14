"""
tests/test_monte_carlo_modes.py — Phase 2 (P1) regression tests.

Guards the Phase-2 behaviours:

* base_case Monte Carlo reconciles with the deterministic DCF (acceptance #5):
  the 0-perturbation anchor equals the DCF point value.
* negative operating margins survive (no artificial "+2%" floor): a
  cash-burning company keeps a negative margin so distress is representable.
* without a DCF anchor (banks/insurers on cost-of-equity caliber, or an
  unsolved DCF) base_case falls back to the independent historical mode.
* reproducibility metadata is emitted (mode / seed / requested / valid /
  invalid / truncated / parameter distributions / correlation matrix).
* the operating-scenario family is a SEPARATE family from the discount-rate
  Bear/Base/Bull (which only moves WACC / terminal growth).
* the report says "Equity Value Wipeout Probability", never the misleading
  "P(股权价值归零 / 资不抵债)".
"""
from __future__ import annotations

import pytest

from analysis.scenario import ScenarioAnalyzer
from classification.classifier import BusinessClassifier
from data import DataValidator, FinancialNormalizer, SyntheticDataProvider
from models.router import ModelRouter
from reporting.dashboard import ValuationReportBuilder
from simulation.monte_carlo import (
    DRIVER_LABELS,
    MODE_BASE_CASE,
    MODE_HISTORICAL,
    MonteCarloSimulator,
)


def _load(ticker: str):
    data = SyntheticDataProvider().get_financial_data(ticker)
    data = FinancialNormalizer.normalize_all(data)
    data = DataValidator.validate(data)
    profile = BusinessClassifier().classify(data)
    return data, profile


def _dcf_value(data, profile):
    r = ModelRouter().run_all(data, profile).get("DCF")
    if r is None or not r.is_success():
        return None
    return r.value_per_share


# ---------------------------------------------------------------------------
# Acceptance #5: base_case MC reconciles with the deterministic DCF
# ---------------------------------------------------------------------------

class TestBaseCaseReconciliation:
    @pytest.mark.parametrize("ticker", ["MSFT", "AAPL"])
    def test_anchor_matches_dcf(self, ticker):
        data, profile = _load(ticker)
        dcf = _dcf_value(data, profile)
        assert dcf is not None and dcf > 0
        res = MonteCarloSimulator().run(data, profile, mode=MODE_BASE_CASE, dcf_value=dcf)
        assert res.mode == MODE_BASE_CASE
        assert res.anchor_value is not None
        assert res.reconcile_gap is not None
        assert abs(res.reconcile_gap) < 1e-3, (
            f"{ticker}: base-case anchor ${res.anchor_value:.2f} vs DCF ${dcf:.2f} "
            f"→ gap {res.reconcile_gap:+.2%} (must reconcile)"
        )

    def test_pre_profit_anchor_floored_like_dcf(self):
        # NBIS: the DCF floors negative equity to 0 (equity wipeout). The MC
        # anchor must use the SAME convention so the two reconcile.
        data, profile = _load("NBIS")
        dcf = _dcf_value(data, profile)
        assert dcf is not None and abs(dcf) < 1e-9
        res = MonteCarloSimulator().run(data, profile, mode=MODE_BASE_CASE, dcf_value=dcf)
        assert res.anchor_value is not None and res.anchor_value >= 0
        assert res.reconcile_gap == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# No artificial margin floor / negative margins preserved
# ---------------------------------------------------------------------------

class TestMarginBounds:
    def test_negative_margin_preserved(self):
        data, profile = _load("NBIS")
        res = MonteCarloSimulator().run(
            data, profile, mode=MODE_BASE_CASE, dcf_value=_dcf_value(data, profile)
        )
        om_mean = res.param_distributions["operating_margin"]["mean"]
        assert om_mean < 0, (
            f"loss-making company must keep a negative margin mean, got {om_mean:.2%}"
        )

    def test_margin_upper_bound_is_configurable(self):
        from config import DEFAULT_MC_CONFIG

        # Bounds come from config, NOT a hardcoded +2% floor.
        assert DEFAULT_MC_CONFIG.op_margin_lower < 0
        assert DEFAULT_MC_CONFIG.op_margin_upper > 0.50


# ---------------------------------------------------------------------------
# No DCF anchor → fall back to the independent historical mode
# ---------------------------------------------------------------------------

class TestHistoricalFallback:
    def test_bank_falls_back_to_historical(self):
        data, profile = _load("JPM")
        assert _dcf_value(data, profile) is None  # bank: DCF is a forbidden caliber
        res = MonteCarloSimulator().run(data, profile, mode=MODE_BASE_CASE, dcf_value=None)
        assert res.mode == MODE_HISTORICAL
        assert any("回退" in n for n in res.notes), res.notes

    def test_historical_mode_centres_on_history(self):
        from forecasts.forecast import ForecastEngine
        from forecasts.nwc_utils import business_type_from_profile

        data, profile = _load("MSFT")
        _, _, hist_om, *_ = ForecastEngine(
            business_type=business_type_from_profile(profile)
        )._extract_history(data)
        res = MonteCarloSimulator().run(data, profile, mode=MODE_HISTORICAL, dcf_value=None)
        assert res.mode == MODE_HISTORICAL
        assert res.param_distributions["operating_margin"]["mean"] == pytest.approx(
            hist_om, abs=1e-9
        )


# ---------------------------------------------------------------------------
# Reproducibility / audit metadata
# ---------------------------------------------------------------------------

class TestMetadata:
    def test_metadata_present(self):
        data, profile = _load("MSFT")
        res = MonteCarloSimulator().run(
            data, profile, mode=MODE_BASE_CASE, dcf_value=_dcf_value(data, profile)
        )
        assert res.random_seed == 42
        assert res.n_requested == 2000
        assert res.n_valid + res.n_invalid == res.n_requested
        assert set(res.param_distributions) == {
            "revenue_cagr", "operating_margin", "wacc", "terminal_growth"
        }
        assert res.correlation is not None
        assert res.correlation["drivers"] == DRIVER_LABELS

    def test_reproducible_with_seed(self):
        data, profile = _load("MSFT")
        dcf = _dcf_value(data, profile)
        mc = MonteCarloSimulator()
        r1 = mc.run(data, profile, mode=MODE_BASE_CASE, dcf_value=dcf)
        r2 = mc.run(data, profile, mode=MODE_BASE_CASE, dcf_value=dcf)
        assert r1.median_value == r2.median_value
        assert r1.values == r2.values


# ---------------------------------------------------------------------------
# Operating vs discount-rate scenario families
# ---------------------------------------------------------------------------

class TestScenarioSplit:
    def test_operating_empty_for_bank(self):
        data, profile = _load("JPM")
        assert ScenarioAnalyzer().run_operating(data, profile) == {}

    def test_operating_scenarios_marked(self):
        data, profile = _load("MSFT")
        op = ScenarioAnalyzer().run_operating(data, profile)
        assert set(op) == {"Bear", "Base", "Bull"}
        for sv in op.values():
            assert sv.scenario_kind == "operating"
            assert "revenue_mult" in sv.drivers

    def test_discount_scenarios_marked(self):
        data, profile = _load("MSFT")
        disc = ScenarioAnalyzer().run_all(data, profile)
        for sv in disc.values():
            assert sv.scenario_kind in ("discount_rate", "financial")


# ---------------------------------------------------------------------------
# Report wording contract
# ---------------------------------------------------------------------------

class TestWipeoutWording:
    def test_report_uses_wipeout_wording(self):
        data, profile = _load("MSFT")
        res = MonteCarloSimulator().run(
            data, profile, mode=MODE_BASE_CASE, dcf_value=_dcf_value(data, profile)
        )
        text = ValuationReportBuilder._data_section(data, res)
        assert "Equity Value Wipeout Probability" in text
        assert "P(股权价值归零" not in text
        assert "资不抵债" not in text

    def test_report_states_mc_is_assumption_distribution(self):
        data, profile = _load("MSFT")
        res = MonteCarloSimulator().run(
            data, profile, mode=MODE_BASE_CASE, dcf_value=_dcf_value(data, profile)
        )
        text = ValuationReportBuilder._data_section(data, res)
        assert "不是独立估值证据" in text
