"""P0 stability suite for non-finite values (Session #52).

P0-4 fixed the *input* door: a NaN quote no longer produces a fabricated CAGR.
This module covers the rest of the chain the reviewer asked for:

    non-finite input -> intermediate overflow -> solver exception ->
    wrong status -> report output

Each stage is tested separately, because a guard at one stage does not imply a
guard at the next: P0-7 was exactly an intermediate overflow that slipped past
the residual gate while every input was finite.

Invariant under test: a result may only claim SOLVED when every number in it is
finite, and a non-finite value anywhere must surface as a data-quality failure -
never as SOLVED, never as NO_ROOT.
"""

from __future__ import annotations

import copy
import json
import logging
import math

import pytest

from classification.classifier import BusinessClassifier
from config import SolverStatus
from data.normalizer import FinancialNormalizer
from data.providers import SyntheticDataProvider
from data.validator import DataValidator
from models.reverse_dcf import ReverseDCFModel
from models.solved_eligibility import check_solved_eligibility

logging.disable(logging.CRITICAL)

NON_FINITE = (float("nan"), float("inf"), float("-inf"))


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


# ---------------------------------------------- the five requested P0 cases

@pytest.mark.parametrize("bad", NON_FINITE, ids=["nan", "pos_inf", "neg_inf"])
def test_non_finite_price_is_refused(base, bad) -> None:
    """Price NaN / +inf / -inf must all be refused, not valued."""
    r = _calc(base, lambda d: setattr(d.market, "current_price", bad))
    assert r.status != SolverStatus.SOLVED
    assert (r.breakdown or {}).get("implied_revenue_cagr") is None
    assert r.value_per_share is None


@pytest.mark.parametrize("bad", NON_FINITE, ids=["nan", "pos_inf", "neg_inf"])
def test_non_finite_shares_is_refused(base, bad) -> None:
    r = _calc(base, lambda d: setattr(d.ttm, "shares_outstanding", bad))
    assert r.status != SolverStatus.SOLVED
    assert (r.breakdown or {}).get("implied_revenue_cagr") is None


@pytest.mark.parametrize("bad", NON_FINITE, ids=["nan", "pos_inf", "neg_inf"])
def test_solver_never_runs_on_non_finite_target(base, bad) -> None:
    """The solver must refuse before any bracket logic sees the value."""
    data, profile = base
    g, status, notes, _p = ReverseDCFModel()._solve_revenue_cagr(
        data, profile, bad, 0.09, 0.025, 5, cagr_lo=0.0, cagr_hi=0.3,
    )
    assert status == SolverStatus.DATA_QUALITY_ERROR
    assert g is None
    assert notes


@pytest.mark.parametrize("bad", NON_FINITE, ids=["nan", "pos_inf", "neg_inf"])
def test_solver_never_runs_on_non_finite_wacc(base, bad) -> None:
    data, profile = base
    g, status, _n, _p = ReverseDCFModel()._solve_revenue_cagr(
        data, profile, 1e12, bad, 0.025, 5, cagr_lo=0.0, cagr_hi=0.3,
    )
    assert status == SolverStatus.DATA_QUALITY_ERROR
    assert g is None


@pytest.mark.parametrize("bad", NON_FINITE, ids=["nan", "pos_inf", "neg_inf"])
def test_solver_never_runs_on_non_finite_terminal_growth(base, bad) -> None:
    data, profile = base
    g, status, _n, _p = ReverseDCFModel()._solve_revenue_cagr(
        data, profile, 1e12, 0.09, bad, 5, cagr_lo=0.0, cagr_hi=0.3,
    )
    assert status == SolverStatus.DATA_QUALITY_ERROR
    assert g is None


# ------------------------------------- stage A: intermediate overflow (P0-7)

@pytest.mark.parametrize("rev", [1e307, 1e308], ids=["1e307", "1e308"])
def test_finite_input_overflowing_projection_is_data_quality_error(base, rev) -> None:
    """P0-7: finite revenue whose projection overflows must not be SOLVED.

    ``nan > tol`` is False, so the residual gate used to pass a NaN residual and
    report the search bound as a root. The correct outcome is a data-quality
    error: the projection has no meaningful EV to invert.
    """
    r = _calc(base, lambda d: setattr(d.ttm, "revenue", rev))
    assert r.status == SolverStatus.DATA_QUALITY_ERROR, (
        f"finite revenue {rev} produced {r.status}"
    )
    assert (r.breakdown or {}).get("implied_revenue_cagr") is None
    assert r.value_per_share is None


def test_failed_projection_is_nan_not_zero(base) -> None:
    """``_project_ev`` must not disguise a failed projection as EV = 0.

    A zero EV is reachable and would be inverted into a confident root.
    """
    data, profile = base
    d = copy.deepcopy(data)
    d.ttm.revenue = 0.0
    ev = ReverseDCFModel()._project_ev(d, profile, 0.10, 0.09, 0.025, 5)
    assert not math.isfinite(ev), f"failed projection returned {ev}"


def test_residual_gate_catches_interior_overflow_with_finite_endpoints(base) -> None:
    """Interior overflow with finite endpoints must not yield a fabricated root.

    In the natural overflow case (EV rising in g) the *endpoint* blows up first
    and the bracket guards catch it, which leaves the residual gate untested.
    This case isolates it: both endpoints are finite and bracket the target, but
    the projection overflows *inside* the interval, so brentq returns a finite
    growth whose EV is NaN.

    Two independent guards defend this: the non-finite-residual gate in the
    brentq branch, and the non-finite-`fm` guard in the bisection fallback that
    runs after brentq raises. Removing either one alone still fails safely -
    verified by mutation - so this test pins the *behaviour*, not one line.
    """
    data, profile = base
    m = ReverseDCFModel()
    real = m._project_ev

    def overflowing(d, prof, g, wacc, tg, horizon, nwc_ratio=None):
        # Finite at the bracket ends, NaN in the interior: the shape a numerical
        # overflow inside the projection window actually produces.
        if g <= -0.45 or g >= 1.45:
            return real(d, prof, g, wacc, tg, horizon, nwc_ratio)
        return float("nan")

    m._project_ev = overflowing
    target = 1e12
    g, status, notes, _p = m._solve_revenue_cagr(
        data, profile, target, 0.09, 0.025, 5, cagr_lo=-0.5, cagr_hi=1.5,
    )
    assert status == SolverStatus.DATA_QUALITY_ERROR, (
        f"interior overflow reported as {status} with cagr={g}"
    )
    assert g is None
    assert notes


def test_residual_gate_rejects_nan_residual_directly(base) -> None:
    """Pin the residual gate in isolation: a NaN residual is never a pass.

    The end-to-end case above is protected by two guards, so it cannot tell
    whether *this* one works. Here brentq is allowed to converge normally and the
    projection is poisoned only *after* it returns, so the non-finite value is
    seen by the residual gate and by nothing else.
    """
    import scipy.optimize

    data, profile = base
    m = ReverseDCFModel()
    real = m._project_ev
    real_brentq = scipy.optimize.brentq
    state = {"poison": False}

    def brentq_then_poison(*a, **k):
        root = real_brentq(*a, **k)
        state["poison"] = True
        return root

    def poisoned(d, prof, g, wacc, tg, horizon, nwc_ratio=None):
        if state["poison"]:
            return float("nan")
        return real(d, prof, g, wacc, tg, horizon, nwc_ratio)

    m._project_ev = poisoned
    scipy.optimize.brentq = brentq_then_poison
    try:
        g, status, notes, _p = m._solve_revenue_cagr(
            data, profile, 1e12, 0.09, 0.025, 5, cagr_lo=-0.5, cagr_hi=1.5,
        )
    finally:
        scipy.optimize.brentq = real_brentq
    assert status == SolverStatus.DATA_QUALITY_ERROR, f"got {status} cagr={g}"
    assert g is None


def test_overflowing_product_of_finite_inputs_is_refused(base) -> None:
    """price and shares can each be finite while their product is inf."""
    r = _calc(base, lambda d: setattr(d.market, "current_price", 1e299))
    assert r.status == SolverStatus.DATA_QUALITY_ERROR
    assert (r.breakdown or {}).get("implied_revenue_cagr") is None


# ------------------------------------------- stage B: reported output finite

def test_solved_outputs_are_all_finite(base) -> None:
    r = _calc(base)
    assert r.status == SolverStatus.SOLVED
    bd = r.breakdown
    for key in ("implied_revenue_cagr", "target_enterprise_value", "implied_wacc"):
        val = bd.get(key)
        if isinstance(val, (int, float)):
            assert math.isfinite(val), f"{key}={val}"
    assert math.isfinite(r.value_per_share)
    assert math.isfinite(r.enterprise_value)


def test_report_payload_is_json_serialisable_without_non_finite(base) -> None:
    """A report consumer must never receive NaN/Infinity tokens.

    ``json.dumps`` emits bare ``NaN``/``Infinity``, which are invalid JSON and
    break strict parsers (Telegram payloads, dashboards). The gate must ensure
    nothing non-finite reaches that boundary.
    """
    r = _calc(base)
    payload = {
        "status": r.status.value,
        "value_per_share": r.value_per_share,
        "enterprise_value": r.enterprise_value,
        "implied_revenue_cagr": (r.breakdown or {}).get("implied_revenue_cagr"),
    }
    text = json.dumps(payload, allow_nan=False)
    assert "NaN" not in text and "Infinity" not in text


# ------------------------------------------- stage C: the eligibility gate

def _gate(**over) -> "object":
    kw = dict(
        price=100.0,
        shares=1e9,
        target_ev=1e11,
        wacc=0.09,
        terminal_growth=0.025,
        solver_meta={
            "converged": True,
            "relative_residual": 1e-12,
            "search_bounds": [-0.5, 1.5],
            "solver_method": "brentq",
        },
        implied_revenue_cagr=0.08,
        value_per_share=100.0,
        growth_band_verdict="SOLVED_WITHIN_BAND",
        recompute_ev=lambda g: 1e11,
    )
    kw.update(over)
    return check_solved_eligibility(**kw)


def test_gate_passes_on_a_clean_solve() -> None:
    assert _gate().ok is True


@pytest.mark.parametrize(
    "field_name,bad",
    [("price", float("nan")), ("shares", float("inf")),
     ("target_ev", float("nan")), ("wacc", float("nan")),
     ("terminal_growth", float("inf"))],
)
def test_gate_rejects_each_non_finite_input(field_name, bad) -> None:
    res = _gate(**{field_name: bad})
    assert res.ok is False
    assert res.failed


def test_gate_rejects_unconverged_solver() -> None:
    res = _gate(solver_meta={"converged": False, "relative_residual": 1.0,
                             "search_bounds": [0, 1], "solver_method": "brentq"})
    assert res.ok is False
    assert any("未收敛" in f for f in res.failed)


def test_gate_rejects_large_residual() -> None:
    res = _gate(solver_meta={"converged": True, "relative_residual": 1e-2,
                             "search_bounds": [0, 1], "solver_method": "brentq"})
    assert res.ok is False
    assert any("残差" in f for f in res.failed)


def test_gate_rejects_nan_residual() -> None:
    """A NaN residual satisfies every bound comparison, so it must be explicit."""
    res = _gate(solver_meta={"converged": True, "relative_residual": float("nan"),
                             "search_bounds": [0, 1], "solver_method": "brentq"})
    assert res.ok is False


def test_gate_rejects_when_root_cannot_be_recomputed() -> None:
    res = _gate(recompute_ev=lambda g: float("nan"))
    assert res.ok is False
    assert any("独立复核" in f for f in res.failed)


def test_gate_rejects_when_recompute_disagrees() -> None:
    res = _gate(recompute_ev=lambda g: 2e11)
    assert res.ok is False


def test_gate_rejects_missing_band_or_root_record() -> None:
    res = _gate(growth_band_verdict=None)
    assert res.ok is False
    res2 = _gate(solver_meta={"converged": True, "relative_residual": 1e-12})
    assert res2.ok is False


def test_gate_requires_independent_recompute_not_omitted() -> None:
    """Omitting the recompute must fail: an unverified promise is not kept."""
    res = _gate(recompute_ev=None)
    assert res.ok is False
    assert any("独立复核" in f for f in res.failed)


def test_solved_result_records_the_gate_verdict(base) -> None:
    """Every SOLVED result must carry its own audit trail."""
    r = _calc(base)
    assert r.status == SolverStatus.SOLVED
    audit = r.breakdown.get("solved_eligibility")
    assert audit is not None
    assert audit["passed"] is True
    assert len(audit["checks"]) == 10
    assert audit["failed"] == []


def test_no_solved_result_ever_has_a_failed_gate(base) -> None:
    """The demotion path must be wired: failed gate ⇒ not SOLVED."""
    for mut in (
        lambda d: setattr(d.market, "current_price", float("nan")),
        lambda d: setattr(d.ttm, "revenue", 1e307),
        lambda d: setattr(d.ttm, "shares_outstanding", float("inf")),
    ):
        r = _calc(base, mut)
        assert r.status != SolverStatus.SOLVED
        audit = (r.breakdown or {}).get("solved_eligibility")
        if audit is not None:
            assert audit["passed"] is False or r.status != SolverStatus.SOLVED


# ------------------------------------- stage D: solver input dependencies

def test_solver_input_dependencies_are_declared(base) -> None:
    """base_fcf must be documented as display-only, not a solver driver."""
    bd = _calc(base).breakdown
    deps = bd.get("solver_input_dependencies")
    assert deps is not None
    assert "base_fcf" in deps["display_only"]
    assert "revenue_ttm" in deps["drivers"]
    assert "operating_margin" in deps["drivers"]
    assert "base_fcf" not in deps["drivers"]


def test_base_fcf_is_not_a_driver_empirically(base) -> None:
    """The declaration must match behaviour: mutating display FCF changes nothing."""
    data, profile = base
    a = copy.deepcopy(data)
    b = copy.deepcopy(data)
    b.ttm.free_cash_flow = 0.0
    ra = ReverseDCFModel().calculate(a, profile)
    rb = ReverseDCFModel().calculate(b, profile)
    assert (ra.breakdown or {}).get("implied_revenue_cagr") == (
        rb.breakdown or {}
    ).get("implied_revenue_cagr")


# ------------------------------------- stage E: local WACC elasticity

def test_wacc_local_elasticity_is_reported_with_its_evaluation_point(base) -> None:
    el = _calc(base).breakdown.get("wacc_local_elasticity")
    assert el is not None
    assert el["dg_dwacc"] is not None and math.isfinite(el["dg_dwacc"])
    # Implied growth rises with the discount rate: a higher required return
    # demands more growth to justify the same price.
    assert el["dg_dwacc"] > 0
    # It is a local property, so the point it was measured at must be recorded.
    for key in ("wacc", "growth", "step", "method"):
        assert key in el


def test_wacc_local_elasticity_matches_a_finite_difference_rerun(base) -> None:
    """Cross-check the reported elasticity against a full re-solve.

    The analytic-ish implicit-function value must agree with what actually
    happens when WACC is bumped and the whole solve is repeated - otherwise the
    reported number describes a different model than the one being solved.
    """
    data, profile = base
    m = ReverseDCFModel()
    r0 = m.calculate(data, profile)
    g0 = r0.breakdown["implied_revenue_cagr"]
    el = r0.breakdown["wacc_local_elasticity"]
    w0 = el["wacc"]

    h = 0.005
    import models.dcf as dcflib

    orig = dcflib.DCFModel._estimate_wacc
    try:
        dcflib.DCFModel._estimate_wacc = lambda self, d, p, *a, **k: w0 + h
        r1 = ReverseDCFModel().calculate(data, profile)
    finally:
        dcflib.DCFModel._estimate_wacc = orig

    g1 = (r1.breakdown or {}).get("implied_revenue_cagr")
    if g1 is None:
        pytest.skip("bumped-WACC solve has no root; elasticity not cross-checkable")
    fd = (g1 - g0) / h
    # Loose factor-of-two band: the finite difference is one-sided and the
    # solve is re-run end-to-end, so exact agreement is not expected.
    assert 0.4 < (el["dg_dwacc"] / fd) < 2.5, (
        f"reported {el['dg_dwacc']:.3f} vs finite-difference {fd:.3f}"
    )
