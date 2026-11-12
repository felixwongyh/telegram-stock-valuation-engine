"""
tests/test_asset_structure_coverage.py - Asset-structure coverage tests

Covers the Session #10 additions:
  * Replacement-cost NAV anchors capital-intensive build-outs (NBIS) so coverage
    no longer collapses to 2 surviving FCF models.
  * REIT (AMT) and Energy (XOM) asset structures route to their archetype models
    and solve end-to-end.
"""
from __future__ import annotations

from classification.classifier import BusinessClassifier
from models.router import ModelRouter
from analysis.model_agreement import ModelAgreementAnalyzer


def _run(data):
    profile = BusinessClassifier().classify(data)
    results = ModelRouter().run_all(data, profile)
    ma = ModelAgreementAnalyzer().analyze(results, data.market.current_price)
    return profile, results, ma


class TestReplacementNAVCoverage:
    def test_capital_intensive_buildout_gets_replacement_nav(self, nbis_data):
        profile = BusinessClassifier().classify(nbis_data)
        assert profile.capital_intensity == "Very Capital Intensive"
        assert "Replacement NAV" in profile.applicable_models

    def test_replacement_nav_solves_with_positive_value(self, nbis_data):
        profile, results, _ = _run(nbis_data)
        r = results.get("Replacement NAV")
        assert r is not None
        assert r.is_success()
        assert r.value_per_share is not None and r.value_per_share > 0
        # Asset base must be reconstructed (Σ capex > Σ D&A)
        assert r.breakdown["net_ppe"] > 0
        assert r.breakdown["shares_outstanding"] > 0

    def test_buildout_coverage_at_least_three_models(self, nbis_data):
        _, _, ma = _run(nbis_data)
        assert ma.n_solved >= 3, f"expected >=3 solved, got {ma.n_solved} ({ma.values})"
        assert ma.n_applicable >= ma.n_solved

    def test_replacement_nav_not_applicable_to_stable_company(self, aapl_data):
        profile = BusinessClassifier().classify(aapl_data)
        assert "Replacement NAV" not in profile.applicable_models


class TestREITStructure:
    def test_amt_classifies_as_reit(self, amt_profile):
        assert amt_profile.business_type == "REIT"
        assert amt_profile.is_reit is True
        assert "REIT NAV" in amt_profile.applicable_models

    def test_amt_reit_nav_solves(self, amt_data):
        _, results, ma = _run(amt_data)
        r = results.get("REIT NAV")
        assert r is not None and r.is_success()
        assert r.value_per_share is not None and r.value_per_share > 0
        assert ma.n_solved >= 3


class TestEnergyStructure:
    def test_xom_classifies_as_energy(self, xom_profile):
        assert xom_profile.business_type == "Energy"

    def test_xom_multiple_and_dcf_models_solve(self, xom_data):
        _, results, ma = _run(xom_data)
        assert results["EV/EBITDA"].is_success()
        assert results["P/E"].is_success()
        assert results["DCF"].is_success()
        assert ma.n_solved >= 4
