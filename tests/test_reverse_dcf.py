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


class TestHorizonIsolation:
    """Session #16 — the horizon must be resolved per call from the profile and
    must never be cached on the shared singleton."""

    @staticmethod
    def _p(bt: str):
        from types import SimpleNamespace
        return SimpleNamespace(business_type=bt)

    def test_reverse_dcf_resolves_per_type(self):
        from config import resolve_forecast_horizon
        m = ReverseDCFModel()
        assert m._resolve_horizon(self._p("SaaS")) == resolve_forecast_horizon("SaaS")
        assert m._resolve_horizon(self._p("Utilities")) == resolve_forecast_horizon("Utilities")
        # Unknown must fall back to the default — NOT inherit Utilities (10).
        assert m._resolve_horizon(self._p("Unknown")) == resolve_forecast_horizon("Unknown")

    def test_reverse_dcf_does_not_mutate_instance_state(self):
        from config import resolve_forecast_horizon
        m = ReverseDCFModel()
        m._resolve_horizon(self._p("Utilities"))
        assert m._resolve_horizon(self._p("Unknown")) == resolve_forecast_horizon("Unknown")
        # No leaked ``horizon`` attribute (the old pollution vector).
        assert not hasattr(m, "horizon")

    def test_dcf_resolves_per_type(self):
        from config import resolve_forecast_horizon
        from models.dcf import DCFModel
        m = DCFModel()
        assert m._resolve_horizon(self._p("Utilities")) == resolve_forecast_horizon("Utilities")
        assert m._resolve_horizon(self._p("Unknown")) == resolve_forecast_horizon("Unknown")

    def test_explicit_override_wins(self):
        from models.dcf import DCFModel
        m = DCFModel(forecast_horizon=9)
        assert m._resolve_horizon(self._p("Utilities")) == 9


class TestConstraintSolver:
    """Session #17 — the constraint-based single-variable solver.

    Hard bounds must report NO_SOLUTION_IN_RANGE (never clamp to the edge);
    monotonicity picks the reachable end; objective errors are INFEASIBLE.
    """

    def test_solves_linear_increasing(self):
        m = ReverseDCFModel()
        s = m._solve_implied_scalar(lambda x: 2.0 * x, 5.0, 0.0, 10.0, True, "x")
        assert s.status == SolverStatus.SOLVED.value
        assert s.value == pytest.approx(2.5, abs=1e-4)
        assert s.rel_residual is not None and s.rel_residual <= m.rcfg.implied_residual_tol

    def test_solves_linear_decreasing(self):
        m = ReverseDCFModel()
        s = m._solve_implied_scalar(lambda x: 10.0 - x, 5.0, 0.0, 10.0, False, "x")
        assert s.status == SolverStatus.SOLVED.value
        assert s.value == pytest.approx(5.0, abs=1e-4)

    def test_target_above_range_is_not_clamped(self):
        m = ReverseDCFModel()
        s = m._solve_implied_scalar(lambda x: 2.0 * x, 1000.0, 0.0, 10.0, True, "营业利润率")
        assert s.status == SolverStatus.NO_SOLUTION_IN_RANGE.value
        assert s.value is None
        assert s.note and ("上界" in s.note)
        assert s.bound_lo == 0.0 and s.bound_hi == 10.0

    def test_target_below_range_is_not_clamped(self):
        m = ReverseDCFModel()
        s = m._solve_implied_scalar(lambda x: 2.0 * x, -1000.0, 0.0, 10.0, True, "x")
        assert s.status == SolverStatus.NO_SOLUTION_IN_RANGE.value
        assert s.value is None
        assert s.note and ("下界" in s.note)

    def test_objective_error_is_infeasible(self):
        m = ReverseDCFModel()

        def boom(_x):
            raise ValueError("no objective")

        s = m._solve_implied_scalar(boom, 1.0, 0.0, 1.0, True, "x")
        assert s.status == SolverStatus.INFEASIBLE.value
        assert s.value is None


class TestImpliedExpectationsPhase2:
    """Session #17 — one-at-a-time implied drivers surfaced in the breakdown."""

    def _ie(self, data, profile):
        m = ReverseDCFModel()
        result = m.calculate(data, profile)
        ie = result.breakdown.get("implied_expectations") or {}
        return m, result, ie

    def test_implied_expectations_populated(self, aapl_data, aapl_profile):
        _, _, ie = self._ie(aapl_data, aapl_profile)
        assert ie.get("method") == "one_at_a_time"
        for key in (
            "implied_operating_margin",
            "implied_fcf_margin",
            "implied_wacc",
            "implied_terminal_growth",
        ):
            assert key in ie, f"missing {key}"

    def test_wacc_and_tg_respect_spread_constraint(self, aapl_data, aapl_profile):
        from forecasts.fcf_projection import MIN_WACC_TG_SPREAD

        _, _, ie = self._ie(aapl_data, aapl_profile)
        base = ie["base_assumptions"]
        ws = ie["implied_wacc"]
        assert ws.bound_lo >= base["terminal_growth"] + MIN_WACC_TG_SPREAD - 1e-9
        gs = ie["implied_terminal_growth"]
        assert gs.bound_hi <= base["wacc"] - MIN_WACC_TG_SPREAD + 1e-9

    def test_implied_operating_margin_roundtrip(self, aapl_data, aapl_profile):
        from forecasts.fcf_projection import project_enterprise_value

        m, result, ie = self._ie(aapl_data, aapl_profile)
        om = ie["implied_operating_margin"]
        if om.value is None:
            pytest.skip("no implied operating margin inside the constraint range")
        target_ev = result.breakdown["target_enterprise_value"]
        base = ie["base_assumptions"]
        horizon = ie["horizon"]
        _, da_ratio, capex_ratio, nwc_ratio, tax_rate = m._bridge_inputs(
            aapl_data, aapl_profile, horizon
        )
        p = project_enterprise_value(
            aapl_data.ttm.revenue, base["revenue_cagr"], om.value, tax_rate,
            da_ratio, capex_ratio, nwc_ratio, base["wacc"], base["terminal_growth"], horizon,
        )
        rel = abs(p.enterprise_value - target_ev) / (abs(target_ev) or 1.0)
        if om.status == SolverStatus.SOLVED.value:
            assert rel <= m.rcfg.implied_residual_tol * 1.5
        else:
            assert om.status in (
                SolverStatus.APPROXIMATE.value,
                SolverStatus.NO_SOLUTION_IN_RANGE.value,
            )
