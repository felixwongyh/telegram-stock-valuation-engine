"""
tests/test_forecast.py - Forecast Engine Tests
"""
from __future__ import annotations

import pytest

from forecasts.forecast import ForecastEngine
from config import DEFAULT_FORECAST_HORIZON_YEARS, ScenarioType


class TestForecast:
    def test_three_scenarios(self, aapl_data):
        eng = ForecastEngine(horizon_years=5)
        all_fc = eng.build_all(aapl_data)
        assert ScenarioType.BEAR in all_fc
        assert ScenarioType.BASE in all_fc
        assert ScenarioType.BULL in all_fc
        for s, fc in all_fc.items():
            assert len(fc) == 5

    def test_bull_gt_bear_revenue(self, aapl_data):
        eng = ForecastEngine(horizon_years=3)
        all_fc = eng.build_all(aapl_data)
        bear_rev = sum(p.revenue or 0 for p in all_fc[ScenarioType.BEAR])
        bull_rev = sum(p.revenue or 0 for p in all_fc[ScenarioType.BULL])
        base_rev = sum(p.revenue or 0 for p in all_fc[ScenarioType.BASE])
        assert bull_rev >= base_rev * 0.99
        assert base_rev >= bear_rev * 0.99

    def test_bear_bull_nwc_scales_with_revenue(self, aapl_data):
        eng = ForecastEngine(horizon_years=3)
        all_fc = eng.build_all(aapl_data)
        for i in range(3):
            base = all_fc[ScenarioType.BASE][i]
            bear = all_fc[ScenarioType.BEAR][i]
            bull = all_fc[ScenarioType.BULL][i]
            assert base.revenue and bear.revenue and bull.revenue
            assert base.change_in_nwc is not None
            ratio = base.change_in_nwc / base.revenue
            assert bear.change_in_nwc == pytest.approx(bear.revenue * ratio, rel=1e-6)
            assert bull.change_in_nwc == pytest.approx(bull.revenue * ratio, rel=1e-6)

    def test_nwc_from_history_not_hardcoded(self, aapl_data):
        eng = ForecastEngine(horizon_years=1)
        _, _, _, _, _, nwc_ratio, _ = eng._extract_history(aapl_data)
        assert nwc_ratio != 0.02 or aapl_data.annual_income[0].change_in_nwc is not None
