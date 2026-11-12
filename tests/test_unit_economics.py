"""
tests/test_unit_economics.py - Unit-economics EV/Sales coverage tests

Covers the Session #11 addition: a *unit-economics-anchored* EV/Sales model for
capital-intensive, pre-profit build-outs (AI cloud / GPU infrastructure), so a
name like NBIS keeps 6 of 7 applicable models alive instead of leaning on a
down-weighted, terminal-value-dominated DCF.

The model values the installed asset base at its *mature* unit economics
(capacity revenue × mature EV/Sales) and discounts the utilisation ramp with the
unified WACC. It is explicitly APPROXIMATE — no GPU-level utilisation/ARPU field
exists, so the revenue-per-asset yield is a derived proxy.
"""
from __future__ import annotations

import pytest

from analysis.model_agreement import ModelAgreementAnalyzer
from classification.classifier import BusinessClassifier
from data import DataValidator, FinancialNormalizer, SyntheticDataProvider
from models.router import ModelRouter
from models.unit_economics import UnitEconomicsSalesModel

MODEL = "EV/Sales (Unit Econ)"


def _load(ticker: str):
    p = SyntheticDataProvider()
    d = p.get_financial_data(ticker)
    d = FinancialNormalizer.normalize_all(d)
    d = DataValidator.validate(d)
    return d


def _run(data):
    profile = BusinessClassifier().classify(data)
    results = ModelRouter().run_all(data, profile)
    ma = ModelAgreementAnalyzer().analyze(results, data.market.current_price)
    return profile, results, ma


class TestRouting:
    def test_buildout_routes_to_unit_economics(self, nbis_data):
        profile = BusinessClassifier().classify(nbis_data)
        assert MODEL in profile.applicable_models

    def test_stable_company_excluded(self, aapl_data):
        profile = BusinessClassifier().classify(aapl_data)
        assert MODEL not in profile.applicable_models

    def test_reit_excluded(self):
        profile = BusinessClassifier().classify(_load("AMT"))
        assert MODEL not in profile.applicable_models

    def test_bank_excluded(self):
        profile = BusinessClassifier().classify(_load("JPM"))
        assert MODEL not in profile.applicable_models


class TestSolving:
    def test_solves_approximate_with_positive_value(self, nbis_data):
        profile, results, _ = _run(nbis_data)
        r = results.get(MODEL)
        assert r is not None
        assert r.is_success()
        assert r.status.value == "Approximate"
        assert r.value_per_share is not None and r.value_per_share > 0

    def test_breakdown_is_internally_consistent(self, nbis_data):
        _, results, _ = _run(nbis_data)
        bd = results[MODEL].breakdown
        assert bd["deployed_capital"] > 0
        assert bd["accumulated_capex"] - bd["accumulated_da"] == pytest.approx(
            bd["deployed_capital"]
        )
        assert 0.0 <= bd["utilisation_gap"] <= 1.0
        assert 0.0 < bd["ramp_discount"] <= 1.0
        # equity → per-share identity
        assert bd["value_per_share"] == pytest.approx(
            bd["equity_value"] / bd["shares_outstanding"], rel=1e-9
        )

    def test_capacity_revenue_floored_at_actual_revenue(self, nbis_data):
        _, results, _ = _run(nbis_data)
        bd = results[MODEL].breakdown
        actual_revenue = nbis_data.ttm.revenue
        assert bd["capacity_revenue"] >= actual_revenue
        assert bd["capacity_revenue"] == pytest.approx(
            max(actual_revenue, bd["deployed_capital"] * bd["benchmark_revenue_yield"])
        )


class TestCoverageImprovement:
    def test_buildout_coverage_at_least_five_models(self, nbis_data):
        _, _, ma = _run(nbis_data)
        assert ma.n_solved >= 5, f"expected >=5 solved, got {ma.n_solved} ({ma.values})"
        assert ma.n_applicable >= ma.n_solved

    def test_coverage_identity_holds(self, nbis_data):
        _, _, ma = _run(nbis_data)
        assert ma.n_applicable == ma.n_solved + ma.n_failed


class TestSensitivityDirection:
    def test_higher_mature_yield_raises_value(self, nbis_data):
        profile = BusinessClassifier().classify(nbis_data)
        m = UnitEconomicsSalesModel()
        low = m.calculate(nbis_data, profile, benchmark_yield=0.25)
        high = m.calculate(nbis_data, profile, benchmark_yield=0.50)
        assert high.value_per_share > low.value_per_share

    def test_longer_ramp_lowers_value(self, nbis_data):
        profile = BusinessClassifier().classify(nbis_data)
        m = UnitEconomicsSalesModel()
        near = m.calculate(nbis_data, profile, ramp_years=1.0)
        far = m.calculate(nbis_data, profile, ramp_years=6.0)
        assert far.value_per_share < near.value_per_share


class TestApplicabilityGuard:
    def test_rejects_non_capital_intensive(self, aapl_data):
        profile = BusinessClassifier().classify(aapl_data)
        ok, reasons = UnitEconomicsSalesModel().applicability_check(aapl_data, profile)
        assert ok is False
        assert reasons
