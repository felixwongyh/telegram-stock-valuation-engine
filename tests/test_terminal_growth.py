"""tests/test_terminal_growth.py — Low < Base < High invariant."""
from __future__ import annotations

from valuation.terminal_growth import TerminalGrowthCalculator


def _bands(data, wacc: float, hint: float):
    return TerminalGrowthCalculator().calculate(data, wacc=wacc, normalized_growth_hint=hint)


class TestTerminalGrowthBands:
    def test_high_growth_gdp_capped_base_still_spreads(self, aapl_data):
        """AVGO-like: Base hits 4.5% GDP cap; High must be 5.0%, not 4.5%."""
        tvg = _bands(aapl_data, wacc=0.1452, hint=0.05)
        assert abs(tvg.low - 0.040) < 1e-9
        assert abs(tvg.base - 0.045) < 1e-9
        assert abs(tvg.high - 0.050) < 1e-9
        assert tvg.low < tvg.base < tvg.high

    def test_mid_growth_symmetric(self, aapl_data):
        tvg = _bands(aapl_data, wacc=0.10, hint=0.030)
        assert abs(tvg.low - 0.025) < 1e-9
        assert abs(tvg.base - 0.030) < 1e-9
        assert abs(tvg.high - 0.035) < 1e-9

    def test_floor_base_keeps_low_strictly_below(self, aapl_data):
        tvg = _bands(aapl_data, wacc=0.10, hint=0.0)
        assert tvg.low < tvg.base < tvg.high
        assert abs(tvg.base - 0.015) < 1e-9
        assert abs(tvg.low - 0.010) < 1e-9
        assert abs(tvg.high - 0.020) < 1e-9

    def test_tight_gordon_bound_slides_window(self, aapl_data):
        """WACC=5% → Gordon cap 4.5%; cannot put High at 5%, so window slides down."""
        tvg = _bands(aapl_data, wacc=0.05, hint=0.05)
        assert tvg.low < tvg.base < tvg.high
        assert tvg.high <= 0.045 + 1e-9
        assert abs(tvg.high - tvg.base - 0.005) < 1e-9
        assert abs(tvg.base - tvg.low - 0.005) < 1e-9

    def test_high_never_equals_base_across_hints(self, aapl_data):
        for hint in (0.0, 0.01, 0.02, 0.03, 0.04, 0.05):
            for wacc in (0.06, 0.08, 0.10, 0.145, 0.20):
                tvg = _bands(aapl_data, wacc=wacc, hint=hint)
                assert tvg.low < tvg.base < tvg.high, (
                    f"failed hint={hint} wacc={wacc}: {tvg.low} {tvg.base} {tvg.high}"
                )
                assert tvg.high < wacc
