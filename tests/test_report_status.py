"""§14 report: explicit final status per ticker, and snapshot provenance.

Two invariants are load-bearing and easy to regress:

* §1.1 - a routed-out ticker must carry an explicit ``MODEL_NOT_APPLICABLE``
  status, never a blank. A blank previously meant both "declined correctly" and
  "never ran", which made the 50 = sum(statuses) check silently unfalsifiable.
* §9 - the snapshot id identifies the *market* snapshot, so all tickers in one
  run share it, and two runs can be told apart without re-reading the market.
"""

from __future__ import annotations

import pytest

from benchmark.report import (
    DATA_ERROR,
    MODEL_NOT_APPLICABLE,
    MULTIPLE_ROOTS,
    NO_SOLUTION,
    NON_CONVERGENT,
    OUT_OF_BAND,
    build_report,
    snapshot_id,
)


def _solved(**over) -> dict:
    f = {
        "ticker": "TEST",
        "risk_free_rate": 0.05,
        "beta_as_of": "2026-11-20",
        "rd_status": "Solved",
        "rd_solver_meta": {"relative_residual": 1e-12, "converged": True,
                           "n_roots_detected": 1, "multiple_roots": False},
        "business_type": "MatureTech",
        "rd_growth_band_verdict": "WITHIN_BASE_BAND",
    }
    f.update(over)
    return f


def test_routed_out_ticker_gets_explicit_status_not_blank() -> None:
    """The §1.1 regression: None + routed_out must resolve to a named status."""
    facts = _solved(rd_status=None, rd_routed_out=True,
                    rd_routed_out_reason="Not applicable for business type Bank",
                    business_type="Bank")
    rep = build_report({"TEST": facts})
    entry = rep["entries"][0]
    assert entry["final_status"] == MODEL_NOT_APPLICABLE
    assert entry["final_status"] != ""
    assert "Bank" in entry["final_status_reason"]


def test_none_without_any_reason_is_a_data_error_not_a_pass() -> None:
    """A silent skip must not masquerade as a clean decline."""
    rep = build_report({"TEST": _solved(rd_status=None, rd_routed_out=False)})
    assert rep["entries"][0]["final_status"] == DATA_ERROR


def test_every_ticker_has_a_status_and_tally_sums_to_count() -> None:
    raw = {
        "A": _solved(ticker="A"),
        "B": _solved(ticker="B", rd_status=None, rd_routed_out=True,
                     business_type="Bank"),
        "C": _solved(ticker="C", rd_status="No Solution In Range"),
    }
    rep = build_report(raw)
    assert rep["ticker_count"] == 3
    assert sum(rep["status_tally"].values()) == 3
    assert all(e["final_status"] for e in rep["entries"])


def test_unconverged_solve_is_not_reported_as_solved() -> None:
    """A root outside the residual bar must not be counted as SOLVED."""
    facts = _solved(rd_solver_meta={
        "relative_residual": 1.2e-4, "converged": False,
        "n_roots_detected": 1, "multiple_roots": False,
    })
    rep = build_report({"TEST": facts})
    assert rep["entries"][0]["final_status"] == NON_CONVERGENT


def test_multiple_roots_are_reported_as_ambiguous() -> None:
    facts = _solved(rd_solver_meta={
        "relative_residual": 1e-12, "converged": True,
        "n_roots_detected": 3, "multiple_roots": True,
    })
    assert build_report({"TEST": facts})["entries"][0]["final_status"] == MULTIPLE_ROOTS


def test_solved_outside_band_is_flagged_not_hidden() -> None:
    facts = _solved(rd_growth_band_verdict="OUTSIDE_BASE_BAND")
    assert build_report({"TEST": facts})["entries"][0]["final_status"] == OUT_OF_BAND


def test_no_solution_is_kept_distinct_from_data_error() -> None:
    """§1.1: mathematical no-solution and bad data are different verdicts."""
    math = build_report({"TEST": _solved(rd_status="No Solution In Range")})
    assert math["entries"][0]["final_status"] == NO_SOLUTION

    bad = build_report({"TEST": _solved(fetch_error="timeout 240s")})
    assert bad["entries"][0]["final_status"] == DATA_ERROR


def test_unmapped_status_raises_instead_of_defaulting() -> None:
    """An unknown solver status must fail loudly, not pick a comfortable label."""
    with pytest.raises(ValueError, match="unmapped rd_status"):
        build_report({"TEST": _solved(rd_status="Something New")})


def test_snapshot_id_is_per_run_not_per_ticker() -> None:
    """All tickers in one market snapshot share an id (§9 provenance)."""
    a = snapshot_id({"risk_free_rate": 0.04912, "beta_as_of": "2026-11-20"})
    b = snapshot_id({"risk_free_rate": 0.04912, "beta_as_of": "2026-11-20",
                     "ticker": "OTHER", "price": 999.0, "beta_used": 2.0})
    assert a == b, "per-ticker values must not change the snapshot id"


def test_snapshot_id_changes_when_market_data_changes() -> None:
    """A different risk-free rate is a different snapshot, so runs are separable."""
    a = snapshot_id({"risk_free_rate": 0.04912, "beta_as_of": "2026-11-20"})
    b = snapshot_id({"risk_free_rate": 0.05052, "beta_as_of": "2026-11-20"})
    assert a != b


def test_report_has_one_snapshot_id_for_the_whole_run() -> None:
    """Declined tickers never read the risk-free rate; that must not split the run.

    Nine routed-out tickers carry ``risk_free_rate=None``. If the id were hashed
    per ticker the run would report two snapshots and look non-reproducible when
    it is not.
    """
    raw = {
        "A": _solved(ticker="A", risk_free_rate=0.04912),
        "B": _solved(ticker="B", risk_free_rate=None, rd_status=None,
                     rd_routed_out=True, business_type="Bank"),
        "C": _solved(ticker="C", risk_free_rate=0.04912),
    }
    rep = build_report(raw)
    assert rep["snapshot_id"].startswith("snap-")
    assert len({e["data_snapshot_id"] for e in rep["entries"]}) == 1
