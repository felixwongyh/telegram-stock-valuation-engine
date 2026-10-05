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
