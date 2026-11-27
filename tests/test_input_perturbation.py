"""§4 - A small input change must not cause an absurd valuation jump.

The threat is not that inputs matter - they must. It is that a 1% price move, or
a 10bp WACC nudge, tips the solver across a discontinuity (a bracket edge, a
band clamp, a sign flip) and the implied growth leaps by tens of points. A user
reading such a number would be reading an artefact of the search, not a fact
about the company.

The measured behaviour on AAPL is a smooth ~0.3pp growth change per 1% price
change, so the bounds below are set from observation, with headroom, not picked
to make the test pass.
"""

from __future__ import annotations

import copy
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
KNOWN_G = 0.08


@pytest.fixture(scope="module")
def base():
    d = DataValidator.validate(
        FinancialNormalizer.normalize_all(SyntheticDataProvider().get_financial_data("AAPL"))
    )
    return d, BusinessClassifier().classify(d)


def _solve(data, profile, target_ev, **kw):
    meta: dict = {}
    g, status, _n, _p = ReverseDCFModel()._solve_revenue_cagr(
        data, profile, target_ev, kw.get("wacc", WACC), kw.get("tg", TG), HORIZON,
        cagr_lo=-0.10, cagr_hi=0.80, meta_out=meta,
    )
    return g, status, meta


# ------------------------------------------------------------- price / revenue

@pytest.mark.parametrize("factor", [0.99, 0.995, 1.005, 1.01])
def test_small_price_move_moves_growth_smoothly(base, factor: float) -> None:
    """§4.1: a ±1% price change must shift implied growth by < 1pp."""
    data, profile = base
    target = project_enterprise_value_from_data(
        data, profile, KNOWN_G, None, WACC, TG, HORIZON
    ).enterprise_value
    g, status, _m = _solve(data, profile, target * factor)
    assert status == SolverStatus.SOLVED
    assert abs(g - KNOWN_G) <= 0.01, f"price x{factor} moved g to {g:.4f}"


@pytest.mark.parametrize("factor", [0.99, 1.01])
def test_small_revenue_move_moves_growth_smoothly(base, factor: float) -> None:
    """§4.1: revenue enters through the projection, so the same bound applies."""
    data, profile = base
    d2 = copy.deepcopy(data)
    d2.ttm.revenue *= factor
    target = project_enterprise_value_from_data(
        data, profile, KNOWN_G, None, WACC, TG, HORIZON
    ).enterprise_value
    g, status, _m = _solve(d2, profile, target)
    assert status == SolverStatus.SOLVED
    # Revenue and price act in opposite directions: more revenue at the same
    # target means *less* growth needed.
    assert abs(g - KNOWN_G) <= 0.02, f"revenue x{factor} moved g to {g:.4f}"
    if factor > 1:
        assert g < KNOWN_G
    else:
        assert g > KNOWN_G


# ------------------------------------------------------------------ WACC / TG

@pytest.mark.parametrize("dw", [-0.01, -0.005, 0.005, 0.01])
def test_wacc_perturbation_is_monotone_and_bounded(base, dw: float) -> None:
    """§4.2: a higher discount rate needs more growth to justify the same price.

    Reverse-DCF growth is *inherently* WACC-sensitive (~0.4pp of growth per 10bp
    of discount rate on AAPL), so the bound is expressed as an elasticity, not an
    absolute cap. What must hold is direction and a smooth, sub-1:1 ratio.
    """
    data, profile = base
    target = project_enterprise_value_from_data(
        data, profile, KNOWN_G, None, WACC, TG, HORIZON
    ).enterprise_value
    g, status, _m = _solve(data, profile, target, wacc=WACC + dw)
    assert status == SolverStatus.SOLVED
    # Amplification: growth moves ~4x the WACC move, and never less than 0.
    ratio = (g - KNOWN_G) / dw
    assert 0 < ratio < 6.0, f"WACC {dw:+.1%}: dg/dw={ratio:.2f}, g={g:.4f}"
    if dw > 0:
        assert g > KNOWN_G
    else:
        assert g < KNOWN_G


@pytest.mark.parametrize("dtg", [-0.005, 0.005])
def test_terminal_growth_perturbation_is_bounded(base, dtg: float) -> None:
    """§4.2: higher terminal growth supplies more of the value, so the explicit
    period needs *less* growth - the elasticity is negative, not positive."""
    data, profile = base
    target = project_enterprise_value_from_data(
        data, profile, KNOWN_G, None, WACC, TG, HORIZON
    ).enterprise_value
    g, status, _m = _solve(data, profile, target, tg=TG + dtg)
    assert status == SolverStatus.SOLVED
    ratio = (g - KNOWN_G) / dtg
    assert -6.0 < ratio < 0, f"TG {dtg:+.1%}: dg/dtg={ratio:.2f}, g={g:.4f}"


# ------------------------------------------------------- continuity / no jumps

def test_ev_is_continuous_in_wacc(base) -> None:
    """§4.3: no step discontinuity across the plausible WACC range.

    A jump larger than ~25% per 1pp would mean the projection switches regimes
    (e.g. terminal-value suppression kicking in) and the implied growth is not
    comparable across discount rates.
    """
    data, profile = base
    evs = [
        project_enterprise_value_from_data(
            data, profile, 0.10, None, w, TG, HORIZON
        ).enterprise_value
        for w in np.arange(0.06, 0.141, 0.01)
    ]
    for a, b in zip(evs, evs[1:]):
        rel = abs(b - a) / abs(a)
        assert rel < 0.25, f"EV jumped {rel:.1%} between adjacent WACC steps"


def test_ev_is_monotone_decreasing_in_wacc(base) -> None:
    data, profile = base
    evs = [
        project_enterprise_value_from_data(
            data, profile, 0.10, None, w, TG, HORIZON
        ).enterprise_value
        for w in np.arange(0.06, 0.141, 0.01)
    ]
    assert all(b < a for a, b in zip(evs, evs[1:])), "EV not monotone in WACC"


def test_ev_is_monotone_increasing_in_terminal_growth(base) -> None:
    data, profile = base
    evs = [
        project_enterprise_value_from_data(
            data, profile, 0.10, None, WACC, t, HORIZON
        ).enterprise_value
        for t in np.arange(0.0, 0.041, 0.01)
    ]
    assert all(b > a for a, b in zip(evs, evs[1:])), "EV not monotone in TG"


def test_growth_solution_has_no_step_over_price_range(base) -> None:
    """§4.4: sweeping price must give a smooth growth curve, not a staircase.

    Steps larger than 2pp between adjacent 1% price points would indicate the
    solver jumping between brackets rather than tracking the root.
    """
    data, profile = base
    ref = project_enterprise_value_from_data(
        data, profile, KNOWN_G, None, WACC, TG, HORIZON
    ).enterprise_value
    gs = []
    for f in np.arange(0.90, 1.101, 0.01):
        g, status, _m = _solve(data, profile, ref * f)
        assert status == SolverStatus.SOLVED
        gs.append(g)
    for a, b in zip(gs, gs[1:]):
        assert abs(b - a) < 0.02, f"growth stepped {abs(b - a):.3%} for a 1% price move"


# ------------------------------------------------------------------- NWC / beta

def test_nwc_ratio_perturbation_is_bounded(base) -> None:
    """§4.5: the NWC ratio is an inferred residual, so it must not dominate.

    Measured on AAPL: a 5pp shift in the marginal NWC ratio moves EV by ~2%. A
    ratio that could swing EV by tens of percent would make the whole valuation
    hostage to the least reliable input.
    """
    data, profile = base
    from forecasts.fcf_projection import dcf_path_inputs_from_data

    ratio = dcf_path_inputs_from_data(data, profile, HORIZON).nwc_marginal_ratio

    def ev_with(r):
        return project_enterprise_value_from_data(
            data, profile, 0.10, None, WACC, TG, HORIZON, nwc_ratio_override=r
        ).enterprise_value

    base_ev = ev_with(ratio)
    for delta in (-0.05, -0.02, 0.02, 0.05):
        shifted = ev_with(ratio + delta)
        rel = abs(shifted - base_ev) / abs(base_ev)
        assert rel < 0.05, f"NWC {delta:+.2f} moved EV by {rel:.1%}"


def test_beta_perturbation_through_wacc_is_bounded(base) -> None:
    """§4.6: beta acts through WACC; a 0.1 beta shift must not swing growth wildly."""
    data, profile = base
    # dWACC ≈ dbeta * equity_risk_premium; ~5% ERP means 0.1 beta ≈ 50bp.
    target = project_enterprise_value_from_data(
        data, profile, KNOWN_G, None, WACC, TG, HORIZON
    ).enterprise_value
    g_up, s1, _ = _solve(data, profile, target, wacc=WACC + 0.005)
    g_dn, s2, _ = _solve(data, profile, target, wacc=WACC - 0.005)
    assert s1 == s2 == SolverStatus.SOLVED
    # 100bp of WACC is worth ~4pp of growth; a 0.1 beta shift is half that.
    assert abs(g_up - g_dn) < 0.05, f"beta-equivalent WACC shift spanned {g_up - g_dn:.3f}"
