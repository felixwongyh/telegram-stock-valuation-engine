"""
tests/test_normalizer.py - Data Normalization Tests
"""
from __future__ import annotations

import pytest

from data import FinancialNormalizer, SyntheticDataProvider


class TestNormalizer:
    def test_ttm_ensured(self):
        d = SyntheticDataProvider().get_financial_data("AAPL")
        d.ttm = None
        d2 = FinancialNormalizer.ensure_ttm(d)
        assert d2.ttm is not None

    def test_derived_fields_filled(self):
        d = SyntheticDataProvider().get_financial_data("MSFT")
        d.ttm.ebitda = None
        d.ttm.ebit = 100.0
        d.ttm.depreciation_amortization = 20.0
        d2 = FinancialNormalizer.fill_derived_fields(d)
        assert abs(d2.ttm.ebitda - 120.0) < 1e-6

    def test_normalize_all(self, aapl_data):
        assert aapl_data.ttm is not None
        assert aapl_data.quality.data_quality_score >= 0

    def test_ttm_sums_change_in_nwc_from_quarters(self):
        from data.models import FinancialStatement

        def q(rev: float, nwc: float) -> FinancialStatement:
            return FinancialStatement(
                period_end="2024-03-31",
                period_type="quarterly",
                revenue=rev,
                operating_income=rev * 0.2,
                depreciation_amortization=rev * 0.02,
                capex=-rev * 0.03,
                free_cash_flow=rev * 0.05,
                change_in_nwc=nwc,
            )

        quarters = [q(100.0, 1.0), q(110.0, 2.0), q(105.0, 1.5), q(115.0, 2.5)]
        ttm = FinancialNormalizer.compute_ttm_from_quarters(quarters)
        assert ttm is not None
        assert ttm.change_in_nwc == pytest.approx(7.0)
