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

    def test_code_table_shows_percent_not_decimal(self, aapl_data, aapl_profile):
        sa = SensitivityAnalyzer(steps=7)
        m = sa.wacc_vs_terminal_growth(aapl_data, aapl_profile)
        table = m.formatted_code_table(max_rows=7, max_cols=7)
        assert "```" in table
        assert "0.145155%" not in table
        assert "%" in table
        sample_wacc = m.rows[0] * 100
        assert f"{sample_wacc:.1f}%" in table or f"{sample_wacc:.2f}%" in table
