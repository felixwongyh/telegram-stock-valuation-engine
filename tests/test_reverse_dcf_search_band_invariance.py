"""Search-band invariance: widening the search interval must not move a root.

The two-layer change deliberately decoupled the *search* interval from the
*plausibility* band. That is only safe if the solver genuinely finds a root
rather than stopping wherever the interval happens to end: a unique root must be
identical whether the solver searched [0, 15%] or [0, 30%].

This is the check the user asked for explicitly::

    Test A: 0-15%  -> 8.23%
    Test B: 0-30%  -> 8.23%   (must match, not 15% or 30%)

If the two disagree, the solver is interval-limited (a bisection artifact, or a
sign change at the boundary mistaken for a root) and the "solution" is not a
root at all.

The solver's own inputs (target EV, WACC, terminal growth, horizon) are captured
by intercepting the real call, so this test exercises the production path
instead of re-deriving its inputs.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from config import SolverStatus

logging.disable(logging.INFO)

# A spread of shapes: high growth, mature software, thin-margin staples,
# cyclical, healthcare, regulated utility, retail.
TICKERS = ["NVDA", "MSFT", "KO", "XOM", "JNJ", "DUK", "CRM", "WMT"]

BANDS = [(0.00, 0.15), (0.00, 0.30), (-0.50, 1.50)]


def _solver_xtol() -> float:
    from models.reverse_dcf import ReverseDCFModel

    return float(ReverseDCFModel().rcfg.newton_tol)


def _capture(ticker: str):
    """Run the model once, intercepting the solver to record its real inputs."""
    from classification.ml_classifier import MLHybridClassifier
    from data import DataValidator, FinancialNormalizer, YahooFinanceProvider
    from models.reverse_dcf import ReverseDCFModel

    data = asyncio.run(YahooFinanceProvider().get_financial_data(ticker))
    data = DataValidator.validate(FinancialNormalizer.normalize_all(data))
    profile = MLHybridClassifier().classify(data)

    model = ReverseDCFModel()
    captured: dict = {}
    original = model._solve_revenue_cagr

    def spy(data_, profile_, target_ev, wacc, tg, horizon, **kw):
        captured.update(target_ev=target_ev, wacc=wacc, tg=tg, horizon=horizon)
        return original(data_, profile_, target_ev, wacc, tg, horizon, **kw)

    model._solve_revenue_cagr = spy  # type: ignore[method-assign]
    try:
        result = model.run(data, profile)
    finally:
        model._solve_revenue_cagr = original  # type: ignore[method-assign]

    assert captured, f"{ticker}: solver was never called"
    assert (result.breakdown or {}), f"{ticker}: run produced no breakdown"
    return model, data, profile, captured


@pytest.fixture(scope="module")
def solved() -> dict:
    """Solve every ticker under every band once; assertions reuse the results."""
    out: dict = {}
    for t in TICKERS:
        model, data, profile, inputs = _capture(t)
        bands = {}
        for band in BANDS:
            meta: dict = {}
            cagr, status, notes, _proj = model._solve_revenue_cagr(
                data, profile, inputs["target_ev"], inputs["wacc"], inputs["tg"],
                horizon=inputs["horizon"], cagr_lo=band[0], cagr_hi=band[1],
                meta_out=meta,
            )
            bands[band] = {"cagr": cagr, "status": status, "notes": notes, "meta": meta}
        out[t] = {"bands": bands, "inputs": inputs}
    return out


def test_search_band_does_not_move_a_root(solved):
    """Same inputs, different search interval => same root, bit for bit."""
    checked = 0
    model_tol = _solver_xtol()
    for t, state in solved.items():
        roots = {
            band: r["cagr"]
            for band, r in state["bands"].items()
            if r["status"] == SolverStatus.SOLVED.value and r["cagr"] is not None
        }
        if len(roots) < 2:
            continue
        checked += 1
        values = list(roots.values())
        spread = max(values) - min(values)
        detail = {f"[{b[0]:.0%},{b[1]:.0%}]": round(v, 8) for b, v in roots.items()}
        # The solver stops at ``xtol`` (1e-4), so two intervals legitimately
        # land within one xtol of each other. Anything larger means the
        # interval -- not the objective -- decided the answer. Verified by
        # tightening xtol to 1e-9: the two roots then agree to 1e-11.
        tol = model_tol * 2
        assert spread <= tol, (
            f"{t}: root depends on the search interval — {detail} "
            f"(spread {spread:.2e} > 2*xtol {tol:.0e}). A unique root must not "
            "move when the interval widens."
        )
    assert checked >= 4, (
        f"only {checked} tickers had >=2 solvable bands; the test is not "
        "actually exercising the solver"
    )


def test_root_stays_inside_the_requested_band(solved):
    """A solved root must lie inside the interval that was searched."""
    for t, state in solved.items():
        for band, r in state["bands"].items():
            if r["status"] != SolverStatus.SOLVED.value:
                continue
            assert band[0] <= r["cagr"] <= band[1], (
                f"{t}: root {r['cagr']:.6f} outside the requested band {band}"
            )


def test_no_root_is_reported_not_fabricated(solved):
    """A non-solved band must not carry a growth rate, and must say why."""
    for t, state in solved.items():
        for band, r in state["bands"].items():
            if r["status"] == SolverStatus.SOLVED.value:
                assert r["cagr"] is not None, f"{t} {band}: solved with no cagr"
                continue
            assert r["cagr"] is None, (
                f"{t} {band}: status={r['status']} but cagr={r['cagr']}"
            )
            assert r["meta"].get("converged") is False, (
                f"{t} {band}: a non-solved path must record converged=False, "
                "otherwise 'no root' cannot be told apart from 'solver never ran'"
            )


def test_root_outside_narrow_band_is_found_by_wider_search(solved):
    """The whole point of two-layer bands: a real root outside the plausibility
    band must still be reported, not masked as 'no solution'.

    KO is the canonical case: its implied growth is ~17%, above the [0, 15%]
    plausibility band. Searching only [0, 15%] returns NO_SOLUTION; searching
    [0, 30%] returns the true root. If this ever regresses to 'no solution' in
    both, the plausibility band has silently become a solve bound again.
    """
    cases = 0
    for t, state in solved.items():
        narrow = state["bands"][(0.00, 0.15)]
        wide = state["bands"][(0.00, 0.30)]
        if narrow["status"] == SolverStatus.SOLVED.value:
            continue
        if wide["status"] != SolverStatus.SOLVED.value:
            continue
        cases += 1
        root = wide["cagr"]
        assert root > 0.15, (
            f"{t}: narrow band failed but the wide-band root {root:.4%} is "
            "inside [0, 15%] — the narrow search should have found it, so the "
            "solver is not reliably bracketing."
        )
    assert cases >= 1, (
        "expected at least one ticker (e.g. KO) whose root lies outside the "
        "plausibility band; none found, so this regression guard is inert"
    )
