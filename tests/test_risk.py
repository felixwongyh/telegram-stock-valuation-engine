"""
tests/test_risk.py - Risk Analysis Tests
"""
from __future__ import annotations

import pytest

from analysis.risk import RiskAnalyzer


class TestRisk:
    def test_risk_runs(self, aapl_data):
        ra = RiskAnalyzer()
        r = ra.analyze(aapl_data, dcf_breakdown=None)
        assert r.overall_score >= 0 and r.overall_score <= 100
        assert r.overall_severity in ("None", "Low", "Medium", "High", "Critical")

    def test_risk_detects_leverage(self, aapl_data):
        ra = RiskAnalyzer()
        r = ra.analyze(aapl_data, dcf_breakdown={"tv_percent_of_ev": 0.90})
        types = {f.risk_type for f in r.flags}
        assert any("Terminal" in t for t in types)
