"""
tests/test_dcf.py - DCF Model Tests
"""
from __future__ import annotations

import pytest

from config import DEFAULT_DCF_CONFIG
from models.dcf import DCFModel
from config import SolverStatus


class TestDCFModel:
    def test_basic_dcf_runs(self, aapl_data, aapl_profile):
        model = DCFModel()
        ok, reasons = model.applicability_check(aapl_data, aapl_profile)
        assert ok, f"Should be applicable: {reasons}"
        result = model.calculate(aapl_data, aapl_profile)
        assert result.is_success(), f"Should succeed: {result.status}"
        assert result.value_per_share is not None
        assert result.value_per_share > 0
        assert "wacc" in result.breakdown
        assert result.breakdown["wacc"] >= DEFAULT_DCF_CONFIG.min_wacc
        assert result.breakdown["wacc"] <= DEFAULT_DCF_CONFIG.max_wacc

    def test_dcf_has_assumptions(self, aapl_data, aapl_profile):
        model = DCFModel()
        result = model.calculate(aapl_data, aapl_profile)
        assert len(result.assumptions) >= 3
        keys = {a.key for a in result.assumptions}
        assert "WACC" in keys
        assert "Terminal Growth" in keys

    def test_dcf_tv_pct_stable(self, aapl_data, aapl_profile):
        model = DCFModel()
        result = model.calculate(aapl_data, aapl_profile)
        assert 0.0 <= result.breakdown.get("tv_percent_of_ev", 0) <= 1.0

    def test_dcf_not_applicable_to_banks(self):
        from data import SyntheticDataProvider, FinancialNormalizer, DataValidator
        from classification.classifier import BusinessClassifier
        d = SyntheticDataProvider().get_financial_data("JPM")
        d = FinancialNormalizer.normalize_all(d)
        d = DataValidator.validate(d)
        p = BusinessClassifier().classify(d)
        model = DCFModel()
        ok, reasons = model.applicability_check(d, p)
        assert not ok
        assert any("financial" in r.lower() for r in reasons)


class TestTerminalValueHonesty:
    """Session #16 — negative terminal FCF must NOT be sign-flipped into a
    fabricated positive terminal value."""

    def test_gordon_suppresses_nonpositive_fcf(self):
        from forecasts.fcf_projection import gordon_terminal_value
        for bad in (-100e6, 0.0, None):
            r = gordon_terminal_value(bad, 0.10, 0.02, 5)
            assert r.suppressed is True
            assert r.terminal_value == 0.0
            assert r.pv_terminal_value == 0.0

    def test_gordon_positive_case_matches_closed_form(self):
        from forecasts.fcf_projection import gordon_terminal_value
        r = gordon_terminal_value(100e6, 0.10, 0.02, 5)
        assert r.suppressed is False
        assert abs(r.terminal_value - (100e6 * 1.02) / 0.08) < 1e-6
        assert abs(r.pv_terminal_value - r.terminal_value / 1.10 ** 5) < 1e-6

    def test_gordon_uses_single_floor_when_wacc_le_g(self):
        from forecasts.fcf_projection import gordon_terminal_value, MIN_WACC_TG_SPREAD
        r = gordon_terminal_value(100e6, 0.02, 0.03, 5)
        assert r.inflated is True
        assert abs(r.terminal_value - (100e6 * 1.03) / MIN_WACC_TG_SPREAD) < 1e-6

    def test_projection_suppresses_tv_for_cash_burner(self):
        from forecasts.fcf_projection import project_enterprise_value
        # Deeply negative FCF (negative margin + heavy capex): terminal year ≤ 0.
        res = project_enterprise_value(
            base_revenue=1e9, revenue_cagr=0.10, operating_margin=-0.20,
            tax_rate=0.21, da_ratio=0.02, capex_ratio=0.50,
            nwc_marginal_ratio=0.02, wacc=0.10, terminal_growth=0.02, horizon=7,
        )
        assert res.fcf_by_year[-1] <= 0
        assert res.terminal_fcf_negative is True
        assert res.pv_terminal == 0.0
        assert res.enterprise_value == res.pv_explicit

    def test_projection_solver_round_trip(self):
        """Forward ↔ inverse projection must agree (self-consistency)."""
        from scipy.optimize import brentq
        from forecasts.fcf_projection import project_enterprise_value
        kw = dict(
            base_revenue=1e9, operating_margin=0.20, tax_rate=0.21,
            da_ratio=0.05, capex_ratio=0.06, nwc_marginal_ratio=0.02,
            wacc=0.09, terminal_growth=0.025, horizon=7,
        )
        g_true = 0.15
        target = project_enterprise_value(revenue_cagr=g_true, **kw).enterprise_value

        def _f(g: float) -> float:
            return project_enterprise_value(revenue_cagr=g, **kw).enterprise_value - target

        g_solved = brentq(_f, -0.05, 0.60, xtol=1e-12)
        assert abs(g_solved - g_true) < 1e-6

    def test_dcf_surfaces_negative_terminal_fcf(self, nbis_data):
        from classification.classifier import BusinessClassifier
        profile = BusinessClassifier().classify(nbis_data)
        result = DCFModel().calculate(nbis_data, profile)
        bd = result.breakdown or {}
        fcf = bd.get("forecast_fcf") or []
        if fcf and fcf[-1] <= 0:
            assert bd.get("terminal_fcf_negative") is True
            assert bd.get("pv_terminal_value") == 0.0
            assert result.status == SolverStatus.APPROXIMATE
            assert any("转型" in n or "turnaround" in n for n in result.notes)
