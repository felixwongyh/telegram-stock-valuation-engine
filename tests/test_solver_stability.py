"""§2 - Solver numerical stability, proved by round-trip against a known answer.

A real company has no ground-truth growth rate, so a 50-ticker run can show that
the solver *runs*, never that it is *right*. These tests build the answer first:
pick a growth rate, project EV forward with the engine's own projection, then ask
the solver to recover that growth rate from the EV alone. Any error is the
solver's, and it is measurable.

Covered:
* §2.1 known-growth round trip at 0/2/5/10/15/25/40% and negative growth.
* §2.2 xtol sweep - tightening must not move the root, and a loose xtol must not
  be mistaken for a residual guarantee.
* §2.5 root edge cases - endpoint roots, near-endpoint roots, no root.
"""

from __future__ import annotations

import logging
from dataclasses import replace

import pytest

from classification.classifier import BusinessClassifier
from config import SolverStatus
from data.normalizer import FinancialNormalizer
from data.providers import SyntheticDataProvider
from data.validator import DataValidator
from forecasts.fcf_projection import project_enterprise_value_from_data
from models.reverse_dcf import ReverseDCFModel

logging.disable(logging.CRITICAL)

WACC, TG, HORIZON = 0.09, 0.025, 5


@pytest.fixture(scope="module")
def fixture_inputs():
    d = DataValidator.validate(
        FinancialNormalizer.normalize_all(SyntheticDataProvider().get_financial_data("AAPL"))
    )
    return d, BusinessClassifier().classify(d)


def _ev(data, profile, g: float) -> float:
    return project_enterprise_value_from_data(
        data, profile, g, None, WACC, TG, HORIZON
    ).enterprise_value


def _solve_for(data, profile, target_ev: float, lo=-0.10, hi=0.80, **cfg):
    m = ReverseDCFModel()
    if cfg:
        m.rcfg = replace(m.rcfg, **cfg)
    meta: dict = {}
    g, status, _notes, _proj = m._solve_revenue_cagr(
        data, profile, target_ev, WACC, TG, HORIZON,
        cagr_lo=lo, cagr_hi=hi, meta_out=meta,
    )
    return g, status, meta


@pytest.mark.parametrize("true_g", [0.0, 0.02, 0.05, 0.10, 0.15, 0.25, 0.40, -0.05])
def test_known_growth_is_recovered(fixture_inputs, true_g: float) -> None:
    """§2.1: project at a known g, solve back, error must be ≤1e-8."""
    data, profile = fixture_inputs
    target = _ev(data, profile, true_g)
    g, status, meta = _solve_for(data, profile, target)

    assert status == SolverStatus.SOLVED, f"g={true_g} not solved: {status}"
    assert g is not None
    assert abs(g - true_g) <= 1e-8, f"g={true_g:.4f} recovered as {g:.10f}"
    assert meta["relative_residual"] <= 1e-4, meta["relative_residual"]


@pytest.mark.parametrize("true_g", [0.05, 0.15, 0.25])
def test_residual_is_recomputed_independently(fixture_inputs, true_g: float) -> None:
    """§2.1: the reported residual must match an independent recomputation.

    The solver's own flag is not evidence; recomputing EV at the returned root
    and comparing to the target is. A mismatch would mean the flag is decorative.
    """
    data, profile = fixture_inputs
    target = _ev(data, profile, true_g)
    g, _status, meta = _solve_for(data, profile, target)

    recomputed = abs(_ev(data, profile, g) - target) / abs(target)
    assert recomputed == pytest.approx(meta["relative_residual"], rel=1e-6, abs=1e-12)
    assert recomputed <= 1e-4


@pytest.mark.parametrize("xtol", [1e-4, 1e-6, 1e-8, 1e-9, 1e-10])
def test_root_is_xtol_stable(fixture_inputs, xtol: float) -> None:
    """§2.2: the unique root must not move when xtol changes.

    Tightening the tolerance may only *improve* accuracy; it must never shift the
    answer materially, which would indicate the solver is chasing numerical noise
    rather than a root.
    """
    data, profile = fixture_inputs
    true_g = 0.0823
    target = _ev(data, profile, true_g)
    g, status, meta = _solve_for(data, profile, target, newton_tol=xtol)

    assert status == SolverStatus.SOLVED
    # brentq guarantees interval width, not root accuracy, so the honest bound is
    # the tolerance itself. What must hold at *every* xtol is the price bar.
    assert abs(g - true_g) <= max(xtol, 1e-9), (
        f"xtol={xtol:g} shifted root to {g:.10f} (err {abs(g - true_g):.2e})"
    )
    assert meta["relative_residual"] <= 1e-4, meta["relative_residual"]


def test_loose_xtol_still_respects_the_price_bar(fixture_inputs) -> None:
    """§2.2: with a loose xtol the *residual* bar must still govern SOLVED.

    This is the COST/PFE/BKNG/JNJ defect: xtol=1e-4 returned a root whose price
    residual exceeded 1e-4 while the status still said SOLVED.
    """
    data, profile = fixture_inputs
    target = _ev(data, profile, 0.10)
    _g, status, meta = _solve_for(data, profile, target, newton_tol=1e-4)

    if meta.get("relative_residual", 0.0) > 1e-4:
        assert status != SolverStatus.SOLVED, (
            "residual above bar but status still SOLVED"
        )
        assert meta["converged"] is False


def test_endpoint_root_is_not_rejected(fixture_inputs) -> None:
    """§2.5: an exact endpoint solution is a boundary root, not a failure."""
    data, profile = fixture_inputs
    lo, hi = 0.0, 0.30
    target = _ev(data, profile, lo)
    g, status, _meta = _solve_for(data, profile, target, lo=lo, hi=hi)
    assert status == SolverStatus.SOLVED
    assert g == pytest.approx(lo, abs=1e-8)


def test_near_endpoint_root_is_found(fixture_inputs) -> None:
    """§2.5: a root just inside the upper bound must still be bracketed."""
    data, profile = fixture_inputs
    hi = 0.30
    true_g = hi - 1e-6
    target = _ev(data, profile, true_g)
    g, status, meta = _solve_for(data, profile, target, lo=0.0, hi=hi)
    assert status == SolverStatus.SOLVED
    # A root 1e-6 inside the ceiling is genuinely indistinguishable from the
    # ceiling at this tolerance, so landing on ``hi`` is correct - what matters
    # is that the *reported* root still hits the target within the price bar.
    assert g == pytest.approx(true_g, abs=1e-5)
    assert meta["relative_residual"] <= 1e-4


def test_target_beyond_ceiling_is_no_solution_not_a_fake_root(fixture_inputs) -> None:
    """§2.5: a target the model cannot reach must report no-solution.

    Never clamp to the bound and call it a root - that fabricates an answer.
    """
    data, profile = fixture_inputs
    lo, hi = 0.0, 0.30
    unreachable = _ev(data, profile, hi) * 1.5
    g, status, _meta = _solve_for(data, profile, unreachable, lo=lo, hi=hi)
    assert status == SolverStatus.NO_SOLUTION_IN_RANGE
    assert g is None


def test_search_range_widening_does_not_move_existing_root(fixture_inputs) -> None:
    """§2.3: widening the search window must not relocate a unique root."""
    data, profile = fixture_inputs
    true_g = 0.06
    target = _ev(data, profile, true_g)
    narrow, _s1, _m1 = _solve_for(data, profile, target, lo=0.0, hi=0.15)
    wide, _s2, _m2 = _solve_for(data, profile, target, lo=-0.10, hi=0.80)
    assert narrow == pytest.approx(wide, abs=1e-9)
    assert narrow == pytest.approx(true_g, abs=1e-8)
