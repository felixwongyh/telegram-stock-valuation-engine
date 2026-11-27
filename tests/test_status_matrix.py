"""§8/§9 - The 50-stock matrix: every status must be earned and explained.

§8 asserts the matrix is stable and every SOLVED answer carries a real residual.
§9 asserts the harder property: each outcome has a *justification a reader can
audit*. A blank status with no reason is indistinguishable from a crash, so a
decline must name its cause and - where the model was routed out - a direct probe
must agree that the data genuinely does not support a solve.
"""

from __future__ import annotations

import logging
import os

import pytest

logging.disable(logging.CRITICAL)
#: The recorded 50-ticker snapshot these expectations were measured on. Pinned
#: explicitly: keying the cache off the wall clock made the numbers a function
#: of the day the suite happened to run.
SNAPSHOT_ID = "20261123"
os.environ.setdefault("UVE_FREEZE_CACHE", "1")
os.environ.setdefault("UVE_SNAPSHOT_ID", SNAPSHOT_ID)

# Kept in sync with the frozen 50-ticker benchmark set.
EXPECTED = {
    "Solved": 32,
    "No Solution In Range": 9,
}
ROUTED_OUT = {"JPM", "BAC", "GS", "CB", "BRK-B", "PLD", "O", "AMT", "VICI"}
FINANCIAL_TYPES = {"Bank", "REIT", "Insurance"}


@pytest.fixture(scope="module")
def facts():
    from benchmark.collector import collect
    from benchmark.registry import tickers

    import asyncio

    async def run():
        out = {}
        for t in tickers():
            out[t] = (await collect(t)).to_dict()
        return out

    return asyncio.run(run())


# ------------------------------------------------------------------ §8 matrix

def test_status_tally_is_stable(facts) -> None:
    """§8.1: the solved / no-solution split must match the recorded matrix."""
    from collections import Counter

    tally = Counter(v.get("rd_status") for v in facts.values())
    assert tally.get("Solved", 0) == EXPECTED["Solved"]
    assert tally.get("No Solution In Range", 0) == EXPECTED["No Solution In Range"]


def test_every_solved_answer_has_a_real_residual(facts) -> None:
    """§8.2: SOLVED without a small residual is a fabricated answer."""
    bad = []
    for t, v in facts.items():
        if v.get("rd_status") != "Solved":
            continue
        res = (v.get("rd_solver_meta") or {}).get("relative_residual")
        if res is None or res > 1e-4:
            bad.append((t, res))
    assert not bad, f"SOLVED with missing/large residual: {bad}"


def test_every_solved_answer_is_finite(facts) -> None:
    """§8.3: no NaN/inf may reach a reported number."""
    import math

    bad = []
    for t, v in facts.items():
        if v.get("rd_status") != "Solved":
            continue
        for key in ("rd_implied_revenue_cagr", "rd_wacc", "rd_value_per_share"):
            val = v.get(key)
            if val is not None and not math.isfinite(float(val)):
                bad.append((t, key, val))
    assert not bad, bad


# ------------------------------------------------------------------- §9 status

def test_no_solution_names_its_cause(facts) -> None:
    """§9.1: a refusal must say why, not leave the reader guessing."""
    bad = []
    for t, v in facts.items():
        if v.get("rd_status") != "No Solution In Range":
            continue
        verdict = v.get("rd_growth_band_verdict")
        notes = v.get("rd_notes") or []
        if not verdict and not notes:
            bad.append(t)
    assert not bad, f"no-solution with no stated cause: {bad}"


def test_no_solution_never_reports_a_cagr(facts) -> None:
    """§9.2: a refusal and a number are mutually exclusive."""
    bad = [
        (t, v.get("rd_implied_revenue_cagr"))
        for t, v in facts.items()
        if v.get("rd_status") == "No Solution In Range"
        and v.get("rd_implied_revenue_cagr") is not None
    ]
    assert not bad, bad


def test_routed_out_names_the_business_type(facts) -> None:
    """§9.3: a routed-out ticker must state the type it was declined for."""
    missing = []
    for t in ROUTED_OUT:
        v = facts.get(t)
        assert v is not None, f"{t} absent from benchmark"
        assert v.get("rd_routed_out") is True, f"{t} not routed out"
        reason = (v.get("rd_routed_out_reason") or "").strip()
        assert reason, f"{t} routed out with no reason"
        assert any(bt in reason for bt in FINANCIAL_TYPES), (
            f"{t} reason does not name a financial type: {reason!r}"
        )
    assert not missing


def test_routed_out_direct_probe_agrees(facts) -> None:
    """§9.4: routing out must be honest - a direct run must also fail to solve.

    If the model would have solved when called directly, the router declined a
    name it could have valued, which is a silent loss of coverage.
    """
    dishonest = []
    for t in ROUTED_OUT:
        v = facts[t]
        direct = v.get("rd_direct_status")
        cagr = v.get("rd_direct_implied_revenue_cagr")
        if direct == "Solved" or cagr is not None:
            dishonest.append((t, direct, cagr))
    assert not dishonest, f"routed out but solvable: {dishonest}"


def test_routed_out_tickers_are_financial_business_types(facts) -> None:
    """§9.5: the excluded names really are banks / REITs / insurers."""
    wrong = {
        t: facts[t].get("business_type")
        for t in ROUTED_OUT
        if facts[t].get("business_type") not in FINANCIAL_TYPES
    }
    assert not wrong, f"routed-out for a non-financial reason: {wrong}"
