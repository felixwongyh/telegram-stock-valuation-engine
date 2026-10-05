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
