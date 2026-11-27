"""Master Validation §14 report: one explicit final status per ticker.

The benchmark stores 86 raw fields per ticker; §14 asks for a different, fixed
set of *reported* fields under a fixed vocabulary. This module is the single
translation layer, so the report never has to guess what a ``None`` meant.

Two invariants it enforces:

* **§1.1** every ticker has an explicit final status. A ticker the router
  declined is ``MODEL_NOT_APPLICABLE`` - not blank. Blank is reserved for a
  genuine data failure, and even then the reason is stated.
* **§9** the report separates *code* changes from *market-data* changes. Each
  entry records the snapshot id and the risk-free rate it used, so two runs can
  be compared without re-reading the market.

Statuses are derived from the recorded facts, never invented: an unmapped
combination raises rather than defaulting to a comfortable label.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from benchmark.registry import BY_TICKER

# ---- final status vocabulary (§1.1) --------------------------------------
SOLVED = "SOLVED"
NO_SOLUTION = "NO_SOLUTION_MATHEMATICAL"      # math says no root in range
DATA_ERROR = "DATA_ERROR"                    # inputs unusable / fetch failed
MODEL_NOT_APPLICABLE = "MODEL_NOT_APPLICABLE"  # correct decline, wrong model
NON_CONVERGENT = "NON_CONVERGENT"            # root exists but bar not met
MULTIPLE_ROOTS = "MULTIPLE_ROOTS"            # ambiguous, not a unique answer
OUT_OF_BAND = "SOLVED_OUTSIDE_ECONOMIC_BAND"  # solved but economically absurd

_STATUS_MAP = {
    "Solved": SOLVED,
    "No Solution In Range": NO_SOLUTION,
    "Insufficient Data": DATA_ERROR,
    "Infeasible Assumptions": NO_SOLUTION,
    # Finite inputs whose projection overflowed to inf/nan: no meaningful EV
    # exists to invert, so this is a data failure - not "no root" (Session #52).
    "Data Quality Error (Non-Finite Projection)": DATA_ERROR,
    "Multiple Roots In Range": MULTIPLE_ROOTS,
    "Non-Monotonic Objective": NON_CONVERGENT,
    "Flat Objective (No Sensitivity)": NON_CONVERGENT,
}


@dataclass
class TickerReport:
    """The §14 field set for one ticker."""

    ticker: str
    company_name: Optional[str]
    business_identity: Optional[str]
    model_route: Optional[str]
    data_snapshot_id: str
    data_quality_status: str
    wacc: Optional[float]
    normalized_fcf: Optional[float]
    beta_used: Optional[float]
    beta_source: Optional[str]
    risk_free_rate: Optional[float]
    implied_revenue_cagr: Optional[float]
    terminal_growth: Optional[float]
    solver_status: Optional[str]
    root_count: int
    relative_residual: Optional[float]
    final_status: str
    final_status_reason: str
    nwc_estimator_method: Optional[str] = None
    nwc_confidence: Optional[str] = None
    growth_band: Optional[str] = None
    extras: dict[str, Any] = field(default_factory=dict)


def snapshot_id(facts: dict[str, Any]) -> str:
    """Stable id of the *market snapshot* a run consumed.

    Hashes only market-wide inputs that moved between runs - the risk-free rate
    and the run's as-of date - so every ticker in one run shares an id, and two
    runs differing only by market data are distinguishable from code drift (§9).
    Per-ticker values (price, beta) are deliberately excluded: they belong to the
    ticker, not to the snapshot.
    """
    basis = {
        "as_of": facts.get("data_as_of") or facts.get("beta_as_of"),
        "rfr": facts.get("risk_free_rate"),
    }
    blob = json.dumps(basis, sort_keys=True, default=str)
    return "snap-" + hashlib.sha256(blob.encode()).hexdigest()[:12]


def _run_snapshot_id(raw: dict[str, dict[str, Any]]) -> str:
    """One snapshot id for the whole run.

    A ticker the router declined never read the risk-free rate, so its own
    ``risk_free_rate`` is ``None``. Hashing per ticker would then split a single
    run into two ids and defeat the purpose. The run-level value is the rate the
    tickers that *did* price actually used, so it is taken from the non-null
    majority.
    """
    rates = [v.get("risk_free_rate") for v in raw.values()
             if v.get("risk_free_rate") is not None]
    as_of = next(
        (v.get("data_as_of") or v.get("beta_as_of") for v in raw.values()
         if (v.get("data_as_of") or v.get("beta_as_of"))),
        None,
    )
    return snapshot_id({"risk_free_rate": max(set(rates), key=rates.count) if rates else None,
                        "data_as_of": as_of})


def _final_status(facts: dict[str, Any], entry: Any) -> tuple[str, str]:
    """Derive the explicit final status plus a human reason. Never blank."""
    raw = facts.get("rd_status")

    if facts.get("fetch_error"):
        return DATA_ERROR, f"fetch failed: {facts['fetch_error']}"

    if raw is None:
        # Router declined. This is the §1.1 hole: None must not be reported as
        # "nothing to say".
        if facts.get("rd_routed_out"):
            reason = facts.get("rd_routed_out_reason") or "routed out by classifier"
            bt = facts.get("business_type") or "unknown business type"
            return (
                MODEL_NOT_APPLICABLE,
                f"reverse DCF not applicable ({bt}); {reason}",
            )
        if entry is not None and not entry.expect_applicable:
            bt = facts.get("business_type") or "unknown business type"
            return MODEL_NOT_APPLICABLE, f"not applicable by registry ({bt})"
        return DATA_ERROR, "no reverse-DCF status and no recorded routing reason"

    mapped = _STATUS_MAP.get(raw)
    if mapped is None:
        raise ValueError(f"{facts.get('ticker')}: unmapped rd_status {raw!r}")

    meta = facts.get("rd_solver_meta") or {}
    rr = meta.get("relative_residual")

    if mapped == SOLVED:
        if meta.get("multiple_roots"):
            return MULTIPLE_ROOTS, "multiple roots detected in range"
        if meta.get("converged") is False:
            return NON_CONVERGENT, f"residual {rr:.3e} above acceptance bar"
        # A NaN residual satisfies ``rr <= bar`` just as it fails ``rr > bar``,
        # so a non-finite residual would be reported SOLVED by a pure threshold
        # test. The report is the last place this can be caught (Session #52).
        if rr is not None and not math.isfinite(rr):
            return DATA_ERROR, "non-finite solver residual; result unusable"
        if meta.get("converged") is None:
            return NON_CONVERGENT, "solver did not record convergence"
        verdict = facts.get("rd_growth_band_verdict")
        if verdict == "OUTSIDE_BASE_BAND":
            return OUT_OF_BAND, "solved, but implied growth is economically implausible"
        return SOLVED, "unique root inside the price residual bar"

    return mapped, f"solver reported {raw!r}"


def build_entry(ticker: str, facts: dict[str, Any]) -> TickerReport:
    entry = BY_TICKER.get(ticker)
    meta = facts.get("rd_solver_meta") or {}
    status, reason = _final_status(facts, entry)

    nwc = facts.get("nwc_shadow") or {}

    return TickerReport(
        ticker=ticker,
        company_name=facts.get("company_name") or (entry.company if entry else None),
        business_identity=facts.get("business_type"),
        model_route=facts.get("expected_route") or (entry.expected_route if entry else None),
        data_snapshot_id=snapshot_id(facts),
        data_quality_status=(
            "DATA_ERROR" if facts.get("fetch_error")
            else ("WARN" if facts.get("validation_warnings") else "OK")
        ),
        wacc=facts.get("rd_wacc") or facts.get("dcf_wacc"),
        normalized_fcf=facts.get("rd_base_fcf"),
        beta_used=facts.get("beta_used"),
        beta_source=facts.get("beta_source"),
        risk_free_rate=facts.get("risk_free_rate"),
        implied_revenue_cagr=facts.get("rd_implied_revenue_cagr"),
        terminal_growth=facts.get("rd_terminal_growth"),
        solver_status=(
            facts.get("rd_status")
            or ("MODEL_NOT_APPLICABLE" if status == MODEL_NOT_APPLICABLE else None)
        ),
        root_count=meta.get("n_roots_detected", 0),
        relative_residual=meta.get("relative_residual"),
        final_status=status,
        final_status_reason=reason,
        nwc_estimator_method=nwc.get("method") or facts.get("nwc_estimator_method"),
        nwc_confidence=nwc.get("confidence") or facts.get("nwc_confidence"),
        growth_band=facts.get("rd_growth_band_verdict"),
    )


def build_report(raw: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Full report plus a status tally that must sum to the ticker count."""
    run_id = _run_snapshot_id(raw)
    entries = [build_entry(t, raw[t]) for t in sorted(raw)]
    for e in entries:
        e.data_snapshot_id = run_id
    tally: dict[str, int] = {}
    for e in entries:
        tally[e.final_status] = tally.get(e.final_status, 0) + 1

    total = sum(tally.values())
    if total != len(raw):
        raise AssertionError(
            f"status tally {total} != ticker count {len(raw)}: {tally}"
        )
    blank = [e.ticker for e in entries if not e.final_status]
    if blank:
        raise AssertionError(f"tickers without a final status: {blank}")

    return {
        "ticker_count": len(raw),
        "status_tally": tally,
        "snapshot_id": run_id,
        "entries": [asdict(e) for e in entries],
    }


__all__ = [
    "TickerReport", "build_report", "build_entry", "snapshot_id",
    "SOLVED", "NO_SOLUTION", "DATA_ERROR", "MODEL_NOT_APPLICABLE",
    "NON_CONVERGENT", "MULTIPLE_ROOTS", "OUT_OF_BAND",
]
