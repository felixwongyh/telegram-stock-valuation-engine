"""
tests/test_reverse_dcf.py - Reverse DCF Solver Tests
"""
from __future__ import annotations

import copy

import pytest

from models.reverse_dcf import ReverseDCFModel
from config import SolverStatus


class TestReverseDCF:
    def test_reverse_dcf_solves(self, aapl_data, aapl_profile):
        model = ReverseDCFModel()
        ok, reasons = model.applicability_check(aapl_data, aapl_profile)
        assert ok, f"Applicability fail: {reasons}"
        result = model.calculate(aapl_data, aapl_profile)
        assert result.status in (SolverStatus.SOLVED, SolverStatus.APPROXIMATE, SolverStatus.NO_SOLUTION_IN_RANGE)
        if result.is_success() or result.status == SolverStatus.NO_SOLUTION_IN_RANGE:
            assert "implied_fcf_cagr" in result.breakdown

    def test_reverse_dcf_outputs_cagr(self, aapl_data, aapl_profile):
        model = ReverseDCFModel()
        result = model.calculate(aapl_data, aapl_profile)
        cagr = result.breakdown.get("implied_fcf_cagr")
        if cagr is not None:
            assert -0.20 <= cagr <= 1.0

    def test_reverse_dcf_rejects_missing_fcf(self, aapl_data, aapl_profile):
        model = ReverseDCFModel()
        data = copy.deepcopy(aapl_data)
        assert data.ttm is not None
        data.ttm.free_cash_flow = None
        data.ttm.operating_cash_flow = None
        data.ttm.capex = None
        ok, reasons = model.applicability_check(data, aapl_profile)
        assert not ok
        assert any("free_cash_flow" in r.lower() or "ocf" in r.lower() for r in reasons)
        result = model.calculate(data, aapl_profile)
        assert result.status == SolverStatus.INSUFFICIENT_DATA
        assert result.breakdown.get("base_fcf") is None
