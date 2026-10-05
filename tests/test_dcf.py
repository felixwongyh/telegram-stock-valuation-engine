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
