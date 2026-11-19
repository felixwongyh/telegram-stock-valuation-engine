"""
tests/test_reverse_dcf.py - Reverse DCF Solver Tests
"""
from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

import models.reverse_dcf as rdm
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
        from forecasts.fcf_projection import project_enterprise_value_shaped

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
        path = ie.get("path_shape") or {}
        p = project_enterprise_value_shaped(
            aapl_data.ttm.revenue, base["revenue_cagr"], om.value, tax_rate,
            da_ratio, capex_ratio, nwc_ratio, base["wacc"], base["terminal_growth"], horizon,
            growth_shape=path.get("growth_shape"),
            margin_offsets=path.get("margin_offsets"),
        )
        rel = abs(p.enterprise_value - target_ev) / (abs(target_ev) or 1.0)
        if om.status == SolverStatus.SOLVED.value:
            assert rel <= m.rcfg.implied_residual_tol * 1.5
        else:
            assert om.status in (
                SolverStatus.APPROXIMATE.value,
                SolverStatus.NO_SOLUTION_IN_RANGE.value,
            )


class _LinearEVModel(ReverseDCFModel):
    """ReverseDCFModel with a synthetic linear EV surface for solver bookkeeping.

    Only ``_project_ev`` is overridden, so the solve orchestration / endpoint-root
    handling / bracket validation can be exercised without a real FCF bridge.
    """

    def __init__(self, base: float, slope: float) -> None:
        super().__init__()
        self._base = base
        self._slope = slope

    def _project_ev(self, data, profile, rev_cagr, wacc, tg, horizon):  # noqa: D401
        return self._base + self._slope * float(rev_cagr)


def _patch_projection(monkeypatch, model, tv_neg: bool = False):
    """Route the module-level projection helper through the synthetic surface."""

    def _fake(data, profile, g, _x, wacc, tg, horizon):
        return SimpleNamespace(
            enterprise_value=model._project_ev(data, profile, g, wacc, tg, horizon),
            terminal_fcf_negative=tv_neg,
            fcf_by_year={},
        )

    monkeypatch.setattr(rdm, "project_enterprise_value_from_data", _fake)


class TestSolverBoundariesSession18:
    """Session #18 P0/P1 — endpoint roots, invalid brackets, non-monotonicity,
    multiple roots and constant objectives must never yield a fake root."""

    # -- 5A: Revenue CAGR exact boundary (endpoint IS a root) --------------
    def test_revenue_cagr_exact_upper_boundary(self, monkeypatch, aapl_data, aapl_profile):
        m = _LinearEVModel(base=100.0, slope=1000.0)
        _patch_projection(monkeypatch, m)
        # EV(0.80) = 100 + 1000*0.80 = 900 → target hits the upper edge exactly.
        rev, status, notes, proj = m._solve_revenue_cagr(
            aapl_data, aapl_profile, 900.0, 0.09, 0.025, 5,
            cagr_lo=-0.10, cagr_hi=0.80,
        )
        assert status == SolverStatus.SOLVED
        assert rev == pytest.approx(0.80, abs=1e-6)

    def test_revenue_cagr_exact_lower_boundary(self, monkeypatch, aapl_data, aapl_profile):
        m = _LinearEVModel(base=100.0, slope=1000.0)
        _patch_projection(monkeypatch, m)
        # EV(-0.10) = 100 - 100 = 0 → target hits the lower edge exactly.
        rev, status, notes, proj = m._solve_revenue_cagr(
            aapl_data, aapl_profile, 0.0, 0.09, 0.025, 5,
            cagr_lo=-0.10, cagr_hi=0.80,
        )
        assert status == SolverStatus.SOLVED
        assert rev == pytest.approx(-0.10, abs=1e-6)

    # -- 1: Bisection must not run on an invalid bracket -------------------
    def test_finish_root_rejects_invalid_bracket(self):
        m = ReverseDCFModel()

        def obj(x: float) -> float:
            # Continuous at the endpoints but the interior is undefined, so
            # brentq fails and f(a)·f(b) > 0 → must refuse to return a root.
            if x == 0.0:
                return -1.0
            if x == 1.0:
                return -2.0
            raise RuntimeError("interior undefined")

        s = m._finish_root(obj, 0.0, 0.0, 1.0, "x", 0.0, 1.0, 1e-6)
        assert s.status == SolverStatus.NO_SOLUTION_IN_RANGE.value
        assert s.value is None
        assert s.note and "bracket" in s.note

    def test_revenue_cagr_no_bracket_returns_no_solution(self, monkeypatch, aapl_data, aapl_profile):
        m = _LinearEVModel(base=0.0, slope=1.0)
        _patch_projection(monkeypatch, m)
        # Target far above EV(hi)=0.80 → f(a)·f(b) > 0 → no bracket.
        rev, status, notes, proj = m._solve_revenue_cagr(
            aapl_data, aapl_profile, 1000.0, 0.09, 0.025, 5,
            cagr_lo=-0.10, cagr_hi=0.80,
        )
        assert rev is None
        assert status == SolverStatus.NO_SOLUTION_IN_RANGE

    # -- 2: Non-monotonic objective with no root --------------------------
    def test_non_monotonic_no_root(self):
        m = ReverseDCFModel()
        # (x-5)^2 has a minimum at 5; target -1 is unreachable → no root.
        s = m._solve_implied_scalar(lambda x: (x - 5.0) ** 2, -1.0, 0.0, 10.0, True, "x")
        assert s.status == SolverStatus.NO_SOLUTION_IN_RANGE.value
        assert s.value is None

    # -- 2: Multiple roots on a non-monotonic surface ---------------------
    def test_multiple_roots_detected(self):
        m = ReverseDCFModel()
        # (x-5)^2 = 0.8 has two roots (≈4.11 and ≈5.89) inside [0, 10].
        s = m._solve_implied_scalar(lambda x: (x - 5.0) ** 2, 0.8, 0.0, 10.0, True, "x")
        assert s.status == SolverStatus.MULTIPLE_ROOTS.value
        assert s.value is None
        assert s.note and "多解" in s.note

    # -- 5B: Constant objective detection ---------------------------------
    def test_constant_objective_flat(self):
        m = ReverseDCFModel()
        s = m._solve_implied_scalar(lambda x: 5.0, 5.0, 0.0, 10.0, True, "终值增长率")
        assert s.status == SolverStatus.FLAT_OBJECTIVE.value
        assert s.value is None
        assert s.note and "敏感度" in s.note

    def test_constant_objective_mismatched_target(self):
        m = ReverseDCFModel()
        s = m._solve_implied_scalar(lambda x: 5.0, 9.0, 0.0, 10.0, True, "x")
        assert s.status == SolverStatus.NO_SOLUTION_IN_RANGE.value
        assert s.value is None


class TestNegativeTerminalFCFSession18:
    """Session #18 P0/P1 — a suppressed terminal value must downgrade the status."""

    def test_finalize_degrades_solved_when_tv_suppressed(self):
        proj = SimpleNamespace(terminal_fcf_negative=True)
        rev, status, notes, _ = ReverseDCFModel._finalize_revenue_cagr(
            0.10, SolverStatus.SOLVED, [], proj
        )
        assert rev == pytest.approx(0.10)
        assert status == SolverStatus.APPROXIMATE
        assert any("终期 FCF" in n for n in notes)

    def test_finalize_keeps_status_when_tv_ok(self):
        proj = SimpleNamespace(terminal_fcf_negative=False)
        _, status, notes, _ = ReverseDCFModel._finalize_revenue_cagr(
            0.10, SolverStatus.SOLVED, [], proj
        )
        assert status == SolverStatus.SOLVED
        assert not any("终期 FCF" in n for n in notes)

    def test_solve_revenue_cagr_propagates_tv_suppression(self, monkeypatch, aapl_data, aapl_profile):
        m = _LinearEVModel(base=100.0, slope=1000.0)
        _patch_projection(monkeypatch, m, tv_neg=True)
        rev, status, notes, proj = m._solve_revenue_cagr(
            aapl_data, aapl_profile, 500.0, 0.09, 0.025, 5,
            cagr_lo=-0.10, cagr_hi=0.80,
        )
        assert rev is not None
        assert status == SolverStatus.APPROXIMATE
        assert getattr(proj, "terminal_fcf_negative", False) is True

    def test_breakdown_and_expectation_expose_suppression(self, aapl_data, aapl_profile):
        from analysis.expectation import ExpectationAnalyzer

        result = ReverseDCFModel().calculate(aapl_data, aapl_profile)
        assert "terminal_fcf_negative" in result.breakdown
        implied = ExpectationAnalyzer().implied_expectations(aapl_data, aapl_profile)
        tv = implied.terminal_fcf_negative
        assert tv is None or isinstance(tv, bool)
        if tv:
            assert any("终值已抑制" in n for n in implied.implied_constraint_notes)

    def test_suppression_backfilled_for_negative_fcf_name(self, nbis_data):
        """NBIS (deeply FCF-negative): the raw CAGR solve has no projection, but
        the implied block detects a suppressed TV — the top-level flag must be
        backfilled (not left as ``None``) and match the expectation layer."""
        from analysis.expectation import ExpectationAnalyzer
        from classification.classifier import BusinessClassifier

        profile = BusinessClassifier().classify(nbis_data)
        result = ReverseDCFModel().calculate(nbis_data, profile)
        flag = result.breakdown.get("terminal_fcf_negative")
        assert flag is not None
        implied = ExpectationAnalyzer().implied_expectations(nbis_data, profile)
        assert implied.terminal_fcf_negative == flag
        if flag:
            assert any("终值已抑制" in n for n in implied.implied_constraint_notes)


class TestImpliedRoundTripsSession18:
    """Session #18 — every implied driver must reproduce the target EV."""

    def _ie(self, data, profile):
        m = ReverseDCFModel()
        result = m.calculate(data, profile)
        return m, result, (result.breakdown.get("implied_expectations") or {})

    def test_fcf_margin_roundtrip(self, aapl_data, aapl_profile):
        from forecasts.fcf_projection import project_enterprise_value_flat_margin

        m, result, ie = self._ie(aapl_data, aapl_profile)
        s = ie["implied_fcf_margin"]
        if s.value is None:
            pytest.skip("no implied FCF margin inside the constraint range")
        target = result.breakdown["target_enterprise_value"]
        base, horizon = ie["base_assumptions"], ie["horizon"]
        shape = (ie.get("path_shape") or {}).get("growth_shape")
        p = project_enterprise_value_flat_margin(
            aapl_data.ttm.revenue, base["revenue_cagr"], s.value,
            base["wacc"], base["terminal_growth"], horizon,
            growth_shape=shape,
        )
        rel = abs(p.enterprise_value - target) / (abs(target) or 1.0)
        if s.status == SolverStatus.SOLVED.value:
            assert rel <= m.rcfg.implied_residual_tol * 1.5

    def test_wacc_roundtrip(self, aapl_data, aapl_profile):
        from forecasts.fcf_projection import project_enterprise_value_shaped

        m, result, ie = self._ie(aapl_data, aapl_profile)
        s = ie["implied_wacc"]
        if s.value is None:
            pytest.skip("no implied WACC inside the constraint range")
        target = result.breakdown["target_enterprise_value"]
        base, horizon = ie["base_assumptions"], ie["horizon"]
        _, da_ratio, capex_ratio, nwc_ratio, tax_rate = m._bridge_inputs(
            aapl_data, aapl_profile, horizon
        )
        path = ie.get("path_shape") or {}
        p = project_enterprise_value_shaped(
            aapl_data.ttm.revenue, base["revenue_cagr"], base["operating_margin"], tax_rate,
            da_ratio, capex_ratio, nwc_ratio, s.value, base["terminal_growth"], horizon,
            growth_shape=path.get("growth_shape"),
            margin_offsets=path.get("margin_offsets"),
        )
        rel = abs(p.enterprise_value - target) / (abs(target) or 1.0)
        if s.status == SolverStatus.SOLVED.value:
            assert rel <= m.rcfg.implied_residual_tol * 1.5

    def test_terminal_growth_roundtrip(self, aapl_data, aapl_profile):
        from forecasts.fcf_projection import project_enterprise_value_shaped

        m, result, ie = self._ie(aapl_data, aapl_profile)
        s = ie["implied_terminal_growth"]
        if s.value is None:
            pytest.skip("no implied terminal growth inside the constraint range")
        target = result.breakdown["target_enterprise_value"]
        base, horizon = ie["base_assumptions"], ie["horizon"]
        _, da_ratio, capex_ratio, nwc_ratio, tax_rate = m._bridge_inputs(
            aapl_data, aapl_profile, horizon
        )
        path = ie.get("path_shape") or {}
        p = project_enterprise_value_shaped(
            aapl_data.ttm.revenue, base["revenue_cagr"], base["operating_margin"], tax_rate,
            da_ratio, capex_ratio, nwc_ratio, base["wacc"], s.value, horizon,
            growth_shape=path.get("growth_shape"),
            margin_offsets=path.get("margin_offsets"),
        )
        rel = abs(p.enterprise_value - target) / (abs(target) or 1.0)
        if s.status == SolverStatus.SOLVED.value:
            assert rel <= m.rcfg.implied_residual_tol * 1.5


class TestMultiTickerStateIsolation:
    """Session #18 — a shared singleton must not leak state between tickers."""

    def test_shared_instance_matches_fresh_instances(self, aapl_data, msft_data, nvda_data):
        from classification.classifier import BusinessClassifier

        clf = BusinessClassifier()
        a = clf.classify(aapl_data)
        ms = clf.classify(msft_data)
        nv = clf.classify(nvda_data)

        shared = ReverseDCFModel()
        shared_results = [
            shared.calculate(aapl_data, a),
            shared.calculate(msft_data, ms),
            shared.calculate(nvda_data, nv),
        ]
        fresh_results = [
            ReverseDCFModel().calculate(aapl_data, a),
            ReverseDCFModel().calculate(msft_data, ms),
            ReverseDCFModel().calculate(nvda_data, nv),
        ]
        for got, exp in zip(shared_results, fresh_results):
            assert got.status == exp.status
            assert got.breakdown.get("implied_revenue_cagr") == exp.breakdown.get("implied_revenue_cagr")

    def test_horizon_not_leaked_between_tickers(self, aapl_data, msft_data):
        from classification.classifier import BusinessClassifier
        from config import resolve_forecast_horizon
        from forecasts.nwc_utils import business_type_from_profile

        clf = BusinessClassifier()
        a = clf.classify(aapl_data)
        ms = clf.classify(msft_data)
        model = ReverseDCFModel()
        assert model._resolve_horizon(a) == resolve_forecast_horizon(business_type_from_profile(a))
        # A second call must reflect the *new* profile, not the previous horizon.
        assert model._resolve_horizon(ms) == resolve_forecast_horizon(business_type_from_profile(ms))
        assert not hasattr(model, "horizon")
