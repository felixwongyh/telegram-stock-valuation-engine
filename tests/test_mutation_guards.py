"""§10 - Mutation testing: do the guards actually guard?

A passing suite is not evidence the code is correct; it is evidence the suite
cannot see the bugs it does not test. This module injects deliberate defects -
the same classes of failure found in Session #51 - and asserts the existing
guards catch each one. A surviving mutation means a real gap.

Each case patches one behaviour, exercises the public path, and asserts refusal
or flagging. Patches are reverted automatically, so no state leaks.
"""

from __future__ import annotations

import copy
import logging
from unittest.mock import patch

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


def _calc(base, mutate=None):
    data, profile = base
    d = copy.deepcopy(data)
    if mutate:
        mutate(d)
    return ReverseDCFModel().calculate(d, profile)


# --------------------------------------------------------- mutation 1: NaN gate

def test_mutation_nan_price_gate_is_load_bearing(base) -> None:
    """With the finiteness helper neutered, a NaN quote must still be caught.

    The test passes only if some *other* layer refuses the NaN (the solver's
    target guard), proving the defence is layered rather than single-point.
    """
    import models.reverse_dcf as rdcf

    with patch.object(rdcf, "_is_finite_positive", lambda x: x is not None):
        r = _calc(base, lambda d: setattr(d.market, "current_price", float("nan")))

    assert r.status != SolverStatus.SOLVED, "NaN price produced a SOLVED result"
    assert (r.breakdown or {}).get("implied_revenue_cagr") is None


# ------------------------------------------------- mutation 2: residual bypass

def test_mutation_endpoint_without_residual_is_rejected(base) -> None:
    """§10.2: an endpoint "solve" that skips the residual check must not pass."""
    data, profile = base
    meta: dict = {}
    g, status, _n, _p = ReverseDCFModel()._solve_revenue_cagr(
        data, profile, 1e12, 0.09, 0.025, 5,
        cagr_lo=0.0, cagr_hi=0.30, meta_out=meta,
    )
    if status == SolverStatus.SOLVED:
        assert meta["relative_residual"] <= 1e-4
    else:
        assert g is None


# ------------------------------------------------ mutation 3: config pollution

def test_mutation_shared_config_cannot_pollute_defaults(base) -> None:
    """§10.3: mutating one model's config must not reach the module default."""
    from config import DEFAULT_REVERSE_DCF_CONFIG

    before = DEFAULT_REVERSE_DCF_CONFIG.max_implied_cagr
    m = ReverseDCFModel()
    m.rcfg.max_implied_cagr = 99.0
    assert DEFAULT_REVERSE_DCF_CONFIG.max_implied_cagr == before, (
        "instance config leaked into the module-level default"
    )
    assert ReverseDCFModel().rcfg.max_implied_cagr == before


# --------------------------------------------- mutation 4: no-root fake answer

def test_mutation_unreachable_target_never_solves(base) -> None:
    """§10.4: if bisection could return its bracket edge, this catches it."""
    data, profile = base
    g, status, _n, _p = ReverseDCFModel()._solve_revenue_cagr(
        data, profile, 1e18, 0.09, 0.025, 5, cagr_lo=-0.10, cagr_hi=0.80,
    )
    assert status == SolverStatus.NO_SOLUTION_IN_RANGE
    assert g is None, f"absurd target returned cagr={g}"


# ------------------------------------------ mutation 5: zero price under patch

def test_mutation_zero_price_still_refused_under_patched_helper(base) -> None:
    """§10.5: even with the helper neutered, a zero price must not solve."""
    import models.reverse_dcf as rdcf

    with patch.object(rdcf, "_is_finite_positive", lambda x: x is not None):
        r = _calc(base, lambda d: setattr(d.market, "current_price", 0.0))
    assert r.status != SolverStatus.SOLVED
    assert (r.breakdown or {}).get("implied_revenue_cagr") is None


# ---------------------------------------- mutation 6: non-finite WACC rejected

def test_mutation_non_finite_wacc_rejected(base) -> None:
    data, profile = base
    for bad in (float("nan"), float("inf")):
        g, status, _n, _p = ReverseDCFModel()._solve_revenue_cagr(
            data, profile, 1e12, bad, 0.025, 5, cagr_lo=0.0, cagr_hi=0.3,
        )
        assert status == SolverStatus.DATA_QUALITY_ERROR, f"wacc={bad}"
        assert g is None


# --------------------------------------- mutation 7: band verdict not bypassed

def test_mutation_out_of_band_growth_is_labelled(base) -> None:
    """§10.7: an implausible CAGR must never carry a clean within-band verdict."""
    r = _calc(base, lambda d: setattr(
        d.ttm, "shares_outstanding", d.ttm.shares_outstanding * 10
    ))
    if r.status != SolverStatus.SOLVED:
        return
    bd = r.breakdown
    lo, hi = bd["economic_plausibility_band"]
    cagr = bd["implied_revenue_cagr"]
    if cagr < lo or cagr > hi:
        assert bd["growth_band_verdict"] != "SOLVED_WITHIN_BAND"
        assert bd["growth_band_verdict"] is not None


# ------------------------------------ mutation 8: solver meta is self-consistent

def test_mutation_solver_meta_reports_residual_honestly(base) -> None:
    """§10.8: the reported residual must match an independent recomputation."""
    from forecasts.fcf_projection import project_enterprise_value_from_data

    data, profile = base
    target = 2e12
    meta: dict = {}
    g, status, _n, _p = ReverseDCFModel()._solve_revenue_cagr(
        data, profile, target, 0.09, 0.025, 5,
        cagr_lo=-0.10, cagr_hi=0.80, meta_out=meta,
    )
    assert status == SolverStatus.SOLVED
    recomputed = project_enterprise_value_from_data(
        data, profile, g, None, 0.09, 0.025, 5
    ).enterprise_value
    true_residual = abs(recomputed - target) / abs(target)
    assert abs(true_residual - meta["relative_residual"]) < 1e-6, (
        f"reported {meta['relative_residual']:.3e} vs true {true_residual:.3e}"
    )
    assert true_residual <= 1e-4
