"""§3 - A SOLVED answer must never be produced from data that cannot support it.

The engine's worst failure is not "no answer": it is a confident number built on
a broken input. Three such paths were found and fixed in Session #51:

* the endpoint short-circuit returned SOLVED without a residual (see
  ``test_false_solved_regressions``);
* a NaN quote passed ``price <= 0`` (False for NaN), yielding ``target_ev=nan``
  and a fabricated CAGR pinned to the search bound;
* an infinite quote did the same.

Everything below asserts *refusal*, and pairs each refusal with a control case so
the suite cannot be satisfied by rejecting everything.
"""

from __future__ import annotations

import copy
import logging
import math

import pytest

from classification.classifier import BusinessClassifier
from config import SolverStatus
from data.normalizer import FinancialNormalizer
from data.providers import SyntheticDataProvider
from data.validator import DataValidator
from models.reverse_dcf import ReverseDCFModel

logging.disable(logging.CRITICAL)


@pytest.fixture(scope="module")
def base():
    d = DataValidator.validate(
        FinancialNormalizer.normalize_all(SyntheticDataProvider().get_financial_data("AAPL"))
    )
    return d, BusinessClassifier().classify(d)


def _calc(base, mutate):
    data, profile = base
    d = copy.deepcopy(data)
    mutate(d)
    return ReverseDCFModel().calculate(d, profile)


def _cagr(result):
    return (result.breakdown or {}).get("implied_revenue_cagr")


# ---------------------------------------------------------------- control case

def test_clean_inputs_solve(base) -> None:
    """Control: without this the refusals below could pass trivially."""
    r = _calc(base, lambda d: None)
    assert r.status == SolverStatus.SOLVED
    assert _cagr(r) is not None


# ------------------------------------------------------- non-finite quotations

@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_price_is_refused(base, bad: float) -> None:
    """NaN defeats ``price <= 0``; finiteness must be tested explicitly."""
    r = _calc(base, lambda d: setattr(d.market, "current_price", bad))
    assert r.status == SolverStatus.INSUFFICIENT_DATA
    assert _cagr(r) is None


@pytest.mark.parametrize("bad", [0, None, -10.0])
def test_invalid_price_is_refused(base, bad) -> None:
    r = _calc(base, lambda d: setattr(d.market, "current_price", bad))
    assert r.status == SolverStatus.INSUFFICIENT_DATA
    assert _cagr(r) is None


@pytest.mark.parametrize("bad", [0, None])
def test_invalid_share_count_is_refused(base, bad) -> None:
    r = _calc(base, lambda d: setattr(d.ttm, "shares_outstanding", bad))
    assert r.status == SolverStatus.INSUFFICIENT_DATA
    assert _cagr(r) is None


# ------------------------------------------------------------ missing financials

def test_missing_ttm_is_refused(base) -> None:
    r = _calc(base, lambda d: setattr(d, "ttm", None))
    assert r.status == SolverStatus.INSUFFICIENT_DATA
    assert _cagr(r) is None


def test_zero_revenue_has_no_root(base) -> None:
    """Zero revenue makes the projection degenerate - must not invent a root."""
    r = _calc(base, lambda d: setattr(d.ttm, "revenue", 0.0))
    # A degenerate projection is a data/numerical-domain failure, not "no root":
    # the maths never ran on a meaningful EV surface (Session #52).
    assert r.status in (
        SolverStatus.DATA_QUALITY_ERROR,
        SolverStatus.NO_SOLUTION_IN_RANGE,
        SolverStatus.INSUFFICIENT_DATA,
    )
    assert _cagr(r) is None


# ------------------------------------------------------- solver-level hardening

def test_solver_refuses_non_finite_target(base) -> None:
    """Defence in depth: the solver itself must reject NaN/inf targets."""
    data, profile = base
    for bad in (float("nan"), float("inf")):
        meta: dict = {}
        g, status, _notes, _proj = ReverseDCFModel()._solve_revenue_cagr(
            data, profile, bad, 0.09, 0.025, 5,
            cagr_lo=0.0, cagr_hi=0.3, meta_out=meta,
        )
        assert status == SolverStatus.DATA_QUALITY_ERROR, f"target={bad}"
        assert g is None


def test_solver_refuses_non_finite_wacc(base) -> None:
    data, profile = base
    g, status, _n, _p = ReverseDCFModel()._solve_revenue_cagr(
        data, profile, 1e12, float("nan"), 0.025, 5, cagr_lo=0.0, cagr_hi=0.3,
    )
    assert status == SolverStatus.DATA_QUALITY_ERROR
    assert g is None


# ------------------------------------------------------- plausible-but-extreme

def test_extreme_growth_is_flagged_not_hidden(base) -> None:
    """A 10x share count needs absurd growth; the engine may still solve it.

    The search band is deliberately wider than the plausibility band, so a
    solvable-but-incredible growth must be *reported as such* rather than
    suppressed or presented as ordinary. What is forbidden is an out-of-band
    growth with a clean verdict.
    """
    r = _calc(base, lambda d: setattr(
        d.ttm, "shares_outstanding", d.ttm.shares_outstanding * 10
    ))
    if r.status != SolverStatus.SOLVED:
        assert _cagr(r) is None
        return

    bd = r.breakdown
    lo, hi = bd["economic_plausibility_band"]
    cagr = _cagr(r)
    assert bd["solver_meta"]["relative_residual"] <= 1e-4
    if not (lo <= cagr <= hi):
        assert bd["growth_band_verdict"] != "SOLVED_WITHIN_BAND", (
            f"implausible CAGR {cagr:.2%} outside [{lo:.0%}, {hi:.0%}] "
            f"reported as within band"
        )
        assert bd["growth_band_verdict"] is not None


def test_halved_revenue_lowers_implied_growth(base) -> None:
    """Direction check: less revenue at the same price needs faster growth."""
    normal = _cagr(_calc(base, lambda d: None))
    halved = _calc(base, lambda d: setattr(d.ttm, "revenue", d.ttm.revenue * 0.5))
    if halved.status == SolverStatus.SOLVED:
        assert _cagr(halved) > normal


# ------------------------------------------------------- output sanity contract

def test_solved_outputs_are_all_finite(base) -> None:
    """No SOLVED result may carry a NaN/inf anywhere in its headline numbers."""
    r = _calc(base, lambda d: None)
    assert r.status == SolverStatus.SOLVED
    bd = r.breakdown
    for key in ("implied_revenue_cagr", "wacc", "terminal_growth",
                "target_enterprise_value", "base_fcf"):
        v = bd.get(key)
        if v is None:
            continue
        assert math.isfinite(float(v)), f"{key} is not finite: {v}"
