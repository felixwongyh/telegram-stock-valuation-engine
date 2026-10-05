"""
tests/test_sensitivity.py - Sensitivity Matrix Tests
"""
from __future__ import annotations

import pytest

from analysis.sensitivity import SensitivityAnalyzer, SENSITIVITY_DEFAULT_STEPS


class TestSensitivity:
    def test_matrix_shape(self, aapl_data, aapl_profile):
        sa = SensitivityAnalyzer(steps=5)
        m = sa.wacc_vs_terminal_growth(aapl_data, aapl_profile)
        assert len(m.rows) == 5
        assert len(m.cols) == 5
        assert len(m.values) == 5
        for row in m.values:
            assert len(row) == 5

    def test_base_within_bounds(self, aapl_data, aapl_profile):
        sa = SensitivityAnalyzer(steps=7)
        m = sa.wacc_vs_terminal_growth(aapl_data, aapl_profile)
        assert 0 <= m.base_row_idx < len(m.rows)
        assert 0 <= m.base_col_idx < len(m.cols)
