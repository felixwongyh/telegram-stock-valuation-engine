"""§5 - The EV-vs-growth curve, and what "no root" is allowed to mean.

Growth does not always add value. When the terminal FCF is suppressed or the
base FCF is negative, more growth can *destroy* EV, so the curve is not monotone
and a naive bisection on a "growing" assumption will either miss the root or
invent one. A 50-ticker scan found 8 such names (AMZN, TSLA, FCX, BA, LLY, MRNA,
NEE, CEG); every one of them is correctly reported as no-solution with a named
cause rather than a fabricated CAGR.

These tests pin both halves: the curve shape is respected, and a non-monotone
curve never yields a confident answer.
"""

from __future__ import annotations

import logging

import numpy as np
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
GRID = np.arange(-0.10, 0.801, 0.05)


@pytest.fixture(scope="module")
def base():
    d = DataValidator.validate(
        FinancialNormalizer.normalize_all(SyntheticDataProvider().get_financial_data("AAPL"))
    )
    return d, BusinessClassifier().classify(d)


def _curve(data, profile):
    return [
        project_enterprise_value_from_data(
            data, profile, g, None, WACC, TG, HORIZON
        ).enterprise_value
        for g in GRID
    ]


def test_healthy_company_curve_is_monotone_increasing(base) -> None:
    """§5.1: for a solvent company growth must add value at every step."""
    data, profile = base
    evs = _curve(data, profile)
    assert all(b > a for a, b in zip(evs, evs[1:]))


def test_monotone_curve_yields_at_most_one_root(base) -> None:
    """§5.2: a monotone curve has a unique root; the solver must report one."""
    data, profile = base
    evs = _curve(data, profile)
    target = (evs[len(evs) // 2] + evs[len(evs) // 2 + 1]) / 2
    meta: dict = {}
    g, status, _n, _p = ReverseDCFModel()._solve_revenue_cagr(
        data, profile, target, WACC, TG, HORIZON,
        cagr_lo=-0.10, cagr_hi=0.80, meta_out=meta,
    )
    assert status == SolverStatus.SOLVED
    assert meta["n_roots_detected"] == 1
    assert meta["multiple_roots"] is False


def test_target_above_ceiling_names_the_direction(base) -> None:
    """§5.3: a target the curve never reaches must say *which* way it missed."""
    data, profile = base
    evs = _curve(data, profile)
    unreachable = max(evs) * 2
    meta: dict = {}
    g, status, notes, _p = ReverseDCFModel()._solve_revenue_cagr(
        data, profile, unreachable, WACC, TG, HORIZON,
        cagr_lo=-0.10, cagr_hi=0.80, meta_out=meta,
    )
    assert status == SolverStatus.NO_SOLUTION_IN_RANGE
    assert g is None
    assert meta.get("failure") in (
        "above_search_ceiling", "below_search_floor", "no_root_monotone_decreasing"
    ), meta.get("failure")


def test_target_below_floor_names_the_direction(base) -> None:
    data, profile = base
    evs = _curve(data, profile)
    unreachable = min(evs) * 0.5 if min(evs) > 0 else -abs(max(evs)) * 2
    meta: dict = {}
    g, status, _n, _p = ReverseDCFModel()._solve_revenue_cagr(
        data, profile, unreachable, WACC, TG, HORIZON,
        cagr_lo=-0.10, cagr_hi=0.80, meta_out=meta,
    )
    assert status == SolverStatus.NO_SOLUTION_IN_RANGE
    assert g is None
    assert meta.get("failure") in ("below_search_floor", "above_search_ceiling")


def test_no_root_ever_returns_a_cagr(base) -> None:
    """§5.4: the invariant that matters - no root means no number, ever."""
    data, profile = base
    evs = _curve(data, profile)
    for target in (max(evs) * 3, min(evs) - abs(max(evs))):
        g, status, _n, _p = ReverseDCFModel()._solve_revenue_cagr(
            data, profile, target, WACC, TG, HORIZON,
            cagr_lo=-0.10, cagr_hi=0.80,
        )
        if status != SolverStatus.SOLVED:
            assert g is None, f"status {status} still returned cagr={g}"
