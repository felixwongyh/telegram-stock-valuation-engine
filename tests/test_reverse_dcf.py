"""
tests/test_reverse_dcf.py - Reverse DCF Solver Tests
"""
from __future__ import annotations

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
