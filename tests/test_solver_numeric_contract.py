"""Solver numeric contract: a reported root must actually hit the target.

Master Validation §6.1 requires that a root be judged by the *price* residual
(``|projected EV - target EV| / target EV``), not merely by how narrow the
search interval became. brentq stops on ``xtol`` (an x-interval width), so a
loose xtol is not a residual guarantee: on the 50-ticker run COST converged with
a 1.18e-4 relative residual and PFE 1.07e-4, both above the 1e-4 acceptance bar,
while still being reported as SOLVED.

These tests pin the contract so the failure cannot come back:

1. the returned root is accurate to ~1e-9 on a smooth synthetic objective;
2. a root that misses the target EV is *downgraded*, never reported SOLVED;
3. the tolerance used is the configured contract value, not a literal.
"""

from __future__ import annotations

import pytest

from config import ReverseDCFConfig, SolverStatus
from models.reverse_dcf import ReverseDCFModel


def _model(**cfg) -> ReverseDCFModel:
    m = ReverseDCFModel()
    for k, v in cfg.items():
        setattr(m.rcfg, k, v)
    return m


def test_root_is_accurate_to_1e9_on_smooth_objective() -> None:
    """A unique root of a smooth, monotone objective is recovered to ~1e-9."""
    true_g = 0.0823
    obj = lambda g: 1000.0 * (1.0 + g) ** 5  # noqa: E731
    r = _model()._solve_implied_scalar(obj, obj(true_g), 0.0, 0.30, True, "synthetic")
    assert r.status == SolverStatus.SOLVED.value
    assert r.value is not None
    assert abs(r.value - true_g) <= 1e-8, f"root error {abs(r.value - true_g):.3e}"


def test_configured_xtol_is_tight_enough_for_the_price_bar() -> None:
    """The shipped xtol must be far tighter than the 1e-4 price residual bar."""
    assert ReverseDCFConfig().newton_tol <= 1e-8


def test_price_residual_tol_is_the_acceptance_bar() -> None:
    """The acceptance bar is 1e-4 relative, not the old hardcoded 1e-3."""
    assert ReverseDCFConfig().price_residual_tol == pytest.approx(1e-4)


def test_residual_threshold_comes_from_config_not_a_literal(
    aapl_data, aapl_profile
) -> None:
    """An impossible bar must prevent SOLVED, proving it is config-driven.

    With ``price_residual_tol=0`` no root can satisfy the bar, so a run that
    would otherwise solve must degrade. If the code used a hardcoded 1e-3 this
    test would still see SOLVED and fail.
    """
    result = _model(price_residual_tol=0.0).run(aapl_data, aapl_profile)
    meta = (result.breakdown or {}).get("solver_meta") or {}
    if meta.get("n_roots_detected", 0) > 0:
        assert result.status != SolverStatus.SOLVED, (
            f"tol=0 still reported SOLVED (residual {meta.get('relative_residual')})"
        )
        assert meta.get("converged") is False


def test_solved_root_satisfies_the_price_bar() -> None:
    """Any SOLVED result must carry a residual inside the acceptance bar."""
    true_g = 0.12
    obj = lambda g: 800.0 * (1.0 + g) ** 6  # noqa: E731
    target = obj(true_g)
    r = _model()._solve_implied_scalar(obj, target, -0.5, 1.5, True, "synthetic")
    assert r.status == SolverStatus.SOLVED.value
    rel = abs(obj(r.value) - target) / abs(target)
    assert rel <= ReverseDCFConfig().implied_residual_tol, f"residual {rel:.3e}"


def test_revenue_cagr_path_reports_residual_within_bar(aapl_data, aapl_profile) -> None:
    """End-to-end: the growth root actually used must meet the price bar.

    This is the path that produced COST/PFE at 1.2e-4, so it is asserted on a
    real model run rather than a synthetic objective.
    """
    tol = ReverseDCFConfig().price_residual_tol
    result = _model().run(aapl_data, aapl_profile)
    meta = (result.breakdown or {}).get("solver_meta") or {}
    if result.status == SolverStatus.SOLVED:
        assert meta.get("converged") is True
        assert meta["relative_residual"] <= tol, meta["relative_residual"]

