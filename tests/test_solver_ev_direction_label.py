"""The solver's no-root `failure` label must name the real cause.

A reverse DCF fails to solve for one of two structurally different reasons, and
the audit trail must not conflate them:

* **EV increasing in growth, target above the ceiling** — ``above_search_ceiling``.
  A higher growth would (if allowed) reach the price; the search range is the
  binding constraint.
* **EV decreasing in growth** — ``ev_decreasing_in_growth``. Growth *destroys*
  modelled value (typically because the terminal FCF is suppressed at ≤ 0, so
  the explicit period carries a negative path). Calling this "above the ceiling"
  is a category error: lowering growth moves *toward* the target.

Before the fix the label was decided purely by ``ev_hi < target_ev``, which
tagged the decreasing case as a ceiling violation. These tests pin the direction
logic so the mislabel cannot come back.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from config import SolverStatus
from models.reverse_dcf import ReverseDCFModel


def _solve_with_ev_curve(monkeypatch, ev_fn, target_ev=1_000.0):
    """Drive ``_solve_revenue_cagr`` with a synthetic EV(g) curve.

    Only the projection is stubbed; the bracket/sign-change/direction logic under
    test is the real production code.
    """
    model = ReverseDCFModel()

    def fake_project(data, profile, g, om, wacc, tg, horizon, **kw):
        return SimpleNamespace(enterprise_value=ev_fn(g))

    monkeypatch.setattr(
        "models.reverse_dcf.project_enterprise_value_from_data", fake_project
    )
    meta: dict = {}
    out = model._solve_revenue_cagr(
        data=SimpleNamespace(ttm=SimpleNamespace(revenue=100.0)),
        profile=SimpleNamespace(business_type="Unknown"),
        target_ev=target_ev,
        wacc=0.09,
        tg=0.02,
        horizon=5,
        cagr_lo=0.0,
        cagr_hi=0.5,
        meta_out=meta,
    )
    return out, meta


def test_increasing_curve_below_target_is_ceiling(monkeypatch) -> None:
    """EV rising but never reaching the target ⇒ genuine ceiling violation."""
    out, meta = _solve_with_ev_curve(monkeypatch, lambda g: 100.0 + 500.0 * g)
    _cagr, status, notes, _proj = out
    assert status == SolverStatus.NO_SOLUTION_IN_RANGE
    assert meta["failure"] == "above_search_ceiling"
    assert meta["ev_direction"] == "increasing"


def test_decreasing_curve_is_not_a_ceiling(monkeypatch) -> None:
    """EV falling as growth rises must NOT be labelled a ceiling violation.

    ``900 - 500g`` sits below the 1000 target at *both* ends and falls with
    growth, so there is no root — and the reason is "EV decreases in growth",
    not "growth is too high" (lower growth is actually closer to the target).
    """
    out, meta = _solve_with_ev_curve(monkeypatch, lambda g: 900.0 - 500.0 * g)
    _cagr, status, notes, _proj = out
    assert status == SolverStatus.NO_SOLUTION_IN_RANGE
    assert meta["failure"] == "ev_decreasing_in_growth"
    assert meta["ev_direction"] == "decreasing"
    assert any("随营收 CAGR 上升而下降" in n for n in notes), (
        "the note must state that EV falls with growth, not that growth is too high"
    )
    assert not any("市场隐含营收 CAGR ≥" in n for n in notes), (
        "a decreasing curve must not be reported as 'implied growth >= ceiling'"
    )
    assert meta["ev_peak_below_target"] is True
    assert meta["ev_peak"] < 1_000.0


def test_decreasing_curve_that_stays_above_target(monkeypatch) -> None:
    """EV decreasing but always above the target ⇒ still no ceiling claim."""
    out, meta = _solve_with_ev_curve(monkeypatch, lambda g: 5000.0 - 1000.0 * g)
    _cagr, status, _notes, _proj = out
    assert status == SolverStatus.NO_SOLUTION_IN_RANGE
    assert meta["failure"] == "ev_decreasing_in_growth"


def test_increasing_curve_above_target_is_floor(monkeypatch) -> None:
    """EV rising and already above target at the low bound ⇒ below-floor case."""
    out, meta = _solve_with_ev_curve(monkeypatch, lambda g: 2000.0 + 500.0 * g)
    _cagr, status, _notes, _proj = out
    assert status == SolverStatus.NO_SOLUTION_IN_RANGE
    assert meta["failure"] == "below_search_floor"
    assert meta["ev_direction"] == "increasing"


@pytest.mark.parametrize(
    "ev_fn",
    [
        lambda g: 2000.0 - 3000.0 * g,   # crosses target: has a root
        lambda g: 100.0 + 5000.0 * g,    # crosses target: has a root
    ],
)
def test_crossing_curve_solves(monkeypatch, ev_fn) -> None:
    """When the curve crosses the target the solver must report SOLVED."""
    out, _meta = _solve_with_ev_curve(monkeypatch, ev_fn)
    _cagr, status, _notes, _proj = out
    assert status in (SolverStatus.SOLVED, SolverStatus.APPROXIMATE)


class TestDecreasingCurveExplanation:
    """The *reason* must match the mechanism, not be assumed.

    The original note asserted "terminal FCF ≤ 0 suppresses the terminal value"
    for every decreasing curve. NEE disproves that: its terminal FCF is positive
    yet EV still falls, because reinvestment (CapEx + working capital) outruns
    the cash the growth produces. These tests pin the two distinct explanations.
    """

    def _meta(self, monkeypatch, ev_fn, target=1_000.0):
        _out, meta = _solve_with_ev_curve(monkeypatch, ev_fn, target_ev=target)
        return meta

    def test_positive_terminal_fcf_is_not_blamed_on_suppression(self, monkeypatch):
        """A decreasing curve with a healthy terminal value gets the
        reinvestment explanation, never the suppression one."""
        meta = self._meta(monkeypatch, lambda g: 900.0 - 500.0 * g)
        assert meta["ev_direction"] == "decreasing"
        assert meta["terminal_fcf_negative_at_peak"] is False
        assert meta["ev_peak_below_target"] is True
        # The peak must be reported so "cannot reach at any growth" is checkable.
        assert "ev_peak" in meta and "ev_peak_growth" in meta

    def test_peak_is_searched_inside_sanctioned_band(self, monkeypatch):
        """The peak growth must lie within the model's own sanctioned band."""
        from models.reverse_dcf import ReverseDCFModel

        cfg = ReverseDCFModel().rcfg
        meta = self._meta(monkeypatch, lambda g: 900.0 - 500.0 * g)
        assert cfg.min_implied_cagr - 1e-9 <= meta["ev_peak_growth"] <= cfg.max_implied_cagr + 1e-9

    def test_suppressed_terminal_value_uses_suppression_wording(self, monkeypatch):
        """When the terminal value *is* suppressed the note says so."""
        from types import SimpleNamespace

        model = ReverseDCFModel()

        def fake_project(data, profile, g, om, wacc, tg, horizon, **kw):
            return SimpleNamespace(
                enterprise_value=900.0 - 500.0 * g,
                terminal_fcf_negative=True,
                fcf_by_year=[-1.0],
            )

        monkeypatch.setattr(
            "models.reverse_dcf.project_enterprise_value_from_data", fake_project
        )
        meta: dict = {}
        _cagr, _status, notes, _proj = model._solve_revenue_cagr(
            data=SimpleNamespace(ttm=SimpleNamespace(revenue=100.0)),
            profile=SimpleNamespace(business_type="Unknown"),
            target_ev=1_000.0, wacc=0.09, tg=0.02, horizon=5,
            cagr_lo=0.0, cagr_hi=0.5, meta_out=meta,
        )
        assert meta["terminal_fcf_negative_at_peak"] is True
        assert any("终期 FCF" in n for n in notes), (
            "a genuinely suppressed terminal value must be named as such"
        )
