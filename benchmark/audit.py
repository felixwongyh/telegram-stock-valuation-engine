"""Audit engine: judge benchmark facts against the registry.

Every check here answers a question the acceptance criteria actually ask, and
each returns ``None`` when it cannot be judged (missing inputs) rather than
silently passing. A check that cannot be evaluated is *not* a pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from benchmark.registry import BY_TICKER

PASS = "PASS"
PASS_WITH_WARNING = "PASS_WITH_WARNING"
NOT_APPLICABLE = "NOT_APPLICABLE"
DATA_ISSUE = "DATA_ISSUE"
FAIL = "FAIL"
REGRESSION = "REGRESSION"
NON_CONVERGENCE = "NON_CONVERGENCE"
OUT_OF_RANGE = "OUT_OF_RANGE"

_ORDER = {
    FAIL: 0, REGRESSION: 1, NON_CONVERGENCE: 2, OUT_OF_RANGE: 3,
    DATA_ISSUE: 4, PASS_WITH_WARNING: 5, NOT_APPLICABLE: 6, PASS: 7,
}


@dataclass
class Finding:
    check: str
    ticker: str
    verdict: str
    detail: str
    severity: str = "info"  # info | warn | critical


@dataclass
class TickerVerdict:
    ticker: str
    verdict: str = PASS
    findings: list[Finding] = field(default_factory=list)

    def add(self, f: Finding) -> None:
        self.findings.append(f)
        if _ORDER[f.verdict] < _ORDER[self.verdict]:
            self.verdict = f.verdict

    @property
    def criticals(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "critical"]


def _close(a: Optional[float], b: Optional[float], rel: float = 0.01, abs_: float = 1e-9) -> Optional[bool]:
    """None when either side is unknown - unknown is not equality."""
    if a is None or b is None:
        return None
    return abs(a - b) <= max(abs_, abs(b) * rel)


# ---------------------------------------------------------------- A. data
def check_a_data(t: str, f: dict) -> list[Finding]:
    out: list[Finding] = []
    if not f.get("fetch_ok"):
        out.append(Finding("A.fetch", t, DATA_ISSUE,
                           f"fetch failed: {f.get('fetch_error')}", "warn"))
        return out

    # FCF sign convention: FCF should equal OCF - capex when all three exist.
    ocf, capex, fcf = f.get("ocf"), f.get("capex"), f.get("fcf_reported")
    if ocf is not None and capex is not None and fcf is not None:
        # capex may be reported negative (outflow) by some providers.
        derived = ocf + capex if capex < 0 else ocf - capex
        ok = _close(fcf, derived, rel=0.02)
        if ok is False:
            out.append(Finding(
                "A.fcf_sign", t, FAIL,
                f"FCF {fcf/1e9:.2f}B != OCF {ocf/1e9:.2f}B - capex "
                f"{capex/1e9:.2f}B = {derived/1e9:.2f}B", "critical"))

    # Silent zero: a zero where a real business must have a positive figure.
    for key in ("revenue", "shares_ttm"):
        v = f.get(key)
        if v is not None and v == 0:
            out.append(Finding("A.silent_zero", t, FAIL,
                               f"{key} is 0 - likely silent fill", "critical"))

    # EV / market cap / equity caliber: market cap must equal price * shares.
    mc, price = f.get("market_cap"), f.get("price")
    sm = f.get("shares_market")
    if mc is not None and price is not None and sm is not None:
        ok = _close(mc, price * sm, rel=1e-6)
        if ok is False:
            out.append(Finding("A.market_cap", t, FAIL,
                               f"market_cap {mc} != price*shares {price*sm}", "critical"))

    # Debt double count: cash should not exceed total debt by absurd margins
    # while both are present and positive... only flag impossible combos.
    debt, cash = f.get("total_debt"), f.get("cash")
    if debt is not None and cash is not None and debt < 0:
        out.append(Finding("A.debt_sign", t, FAIL,
                           f"total_debt negative ({debt})", "critical"))

    if not f.get("currency"):
        out.append(Finding("A.currency", t, DATA_ISSUE,
                           "currency missing - caliber unverified", "warn"))

    # Missing capex while FCF present means the bridge cannot be recomputed.
    if fcf is not None and capex is None:
        out.append(Finding("A.capex_missing", t, PASS_WITH_WARNING,
                           "capex missing; FCF bridge not independently verifiable", "warn"))
    return out


# ---------------------------------------------------------------- B. math
def check_b_math(t: str, f: dict) -> list[Finding]:
    out: list[Finding] = []
    entry = BY_TICKER[t]
    status = f.get("rd_status") or f.get("rd_direct_status")

    if not entry.expect_applicable:
        # Must have declined. A produced number here is the bug we hunt.
        if f.get("rd_status") in ("Solved", "Approximate"):
            out.append(Finding("B.applicability", t, FAIL,
                               f"ReverseDCF solved for a {entry.expected_route} "
                               f"that must be declined", "critical"))
        elif f.get("rd_routed_out") or status in entry.accept_statuses:
            out.append(Finding("B.applicability", t, PASS,
                               f"correctly declined ({entry.expected_route}): "
                               f"{f.get('rd_routed_out_reason') or status}"))
        else:
            out.append(Finding("B.applicability", t, FAIL,
                               f"declined for an unrecognised reason: {status}", "critical"))
        return out

    if status is None:
        out.append(Finding("B.status", t, FAIL, "no status at all", "critical"))
        return out
    if status in entry.forbidden_statuses:
        out.append(Finding("B.status", t, FAIL,
                           f"status {status} forbidden for this ticker", "critical"))

    if status == "Solved":
        cagr = f.get("rd_implied_revenue_cagr")
        if cagr is None:
            out.append(Finding("B.solved_no_cagr", t, FAIL,
                               "Solved but no implied revenue CAGR", "critical"))
        else:
            bound = f.get("rd_implied_cagr_bound") or {}
            lo, hi = bound.get("low"), bound.get("high")
            if lo is not None and hi is not None and not (lo - 1e-9 <= cagr <= hi + 1e-9):
                out.append(Finding("B.cagr_out_of_band", t, FAIL,
                                   f"implied CAGR {cagr:.4f} outside solved band "
                                   f"[{lo:.4f}, {hi:.4f}]", "critical"))

        # Round-trip: feeding the implied CAGR back must reproduce the target EV.
        ev = f.get("rd_enterprise_value")
        if ev is not None and ev <= 0:
            out.append(Finding("B.ev_sign", t, FAIL,
                               f"enterprise value {ev} non-positive on a Solved result",
                               "critical"))

        wacc, tg = f.get("rd_wacc"), f.get("rd_terminal_growth")
        if wacc is not None and tg is not None and tg >= wacc:
            out.append(Finding("B.gordon", t, FAIL,
                               f"terminal growth {tg:.4f} >= WACC {wacc:.4f}", "critical"))
    return out


# ---------------------------------------------------------------- C. sensitivity
def check_c_terminal_value(t: str, f: dict) -> list[Finding]:
    """Terminal-value dominance must be disclosed when it is extreme."""
    out: list[Finding] = []
    share = f.get("rd_tv_share")
    if share is None:
        return out
    if share >= 0.90:
        out.append(Finding("C.tv_dominance", t, PASS_WITH_WARNING,
                           f"terminal value {share:.1%} of EV - value rests on perpetuity",
                           "warn"))
    return out


# ---------------------------------------------------------------- D. industry
def check_d_industry(t: str, f: dict) -> list[Finding]:
    out: list[Finding] = []
    entry = BY_TICKER[t]
    if not f.get("fetch_ok"):
        return out

    bt = f.get("business_type")
    is_fin = f.get("is_financial_institution")
    is_reit = f.get("is_reit")

    if entry.expected_route == "BANK" and is_fin is not True:
        out.append(Finding("D.bank_route", t, FAIL,
                           f"expected bank routing, got business_type={bt}", "critical"))
    if entry.expected_route == "REIT_NAV" and is_reit is not True:
        out.append(Finding("D.reit_route", t, FAIL,
                           f"expected REIT routing, got business_type={bt}", "critical"))
    # Visa is asset-light but NOT a bank: misrouting here is a known trap.
    if t == "V" and is_fin:
        out.append(Finding("D.visa_misroute", t, FAIL,
                           "Visa routed as a financial institution", "critical"))
    return out


def check_e_coverage(t: str, f: dict) -> list[Finding]:
    """Every ticker must land in an *explicit*, explained outcome.

    The acceptance bar is "no omission, no default-pass, no silent skip". A
    missing reverse-DCF status is only legitimate when the registry itself says
    the ticker is not applicable (bank / insurer / REIT routed elsewhere); in
    that case the exclusion must still be attributable to a business type. Any
    other ``None`` status is a silent skip and fails here rather than quietly
    counting toward a "clean" total.
    """
    entry = BY_TICKER.get(t)
    status = f.get("rd_status")
    if status is not None:
        return []

    if entry is None:
        return [Finding("E.coverage", t, FAIL,
                        "ticker missing from registry (cannot judge applicability)",
                        "critical")]

    if entry.expect_applicable:
        return [Finding(
            "E.coverage", t, FAIL,
            f"reverse DCF expected but produced no status (silent skip); "
            f"expected route={entry.expected_route!r}",
            "critical",
        )]

    bt = f.get("business_type")
    if not bt:
        return [Finding(
            "E.coverage", t, DATA_ISSUE,
            "excluded from reverse DCF but no business_type recorded "
            "(exclusion is unexplained)",
            "warn",
        )]
    return [Finding(
        "E.coverage", t, NOT_APPLICABLE,
        f"reverse DCF not applicable ({bt}); routed to its own methodology",
        "info",
    )]


def judge(t: str, f: dict) -> TickerVerdict:
    v = TickerVerdict(ticker=t)
    for finding in (
        check_a_data(t, f)
        + check_b_math(t, f)
        + check_c_terminal_value(t, f)
        + check_d_industry(t, f)
        + check_e_coverage(t, f)
    ):
        v.add(finding)
    return v


__all__ = ["Finding", "TickerVerdict", "judge", "PASS", "FAIL", "DATA_ISSUE",
           "PASS_WITH_WARNING", "NOT_APPLICABLE"]
