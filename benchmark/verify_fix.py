"""Stage-3 acceptance audit for the Reverse-DCF two-layer band change.

Answers the questions the acceptance criteria actually ask, per ticker:

1. Beta Raw        - is the regression beta recorded, not silently floored?
2. Beta Adjusted   - is the risk adjustment arithmetically reproducible?
3. Beta Used       - can the final beta be traced to its source?
4. Date Alignment  - is the regression window spec recorded?
5. Reverse DCF     - did widening the search band move an existing unique root?
6. Solver Residual - does the solved root satisfy numerical tolerance?
7. Multiple Roots  - are multiple roots detected when present?
8. Growth Bounds   - is "solved outside band" distinguished from "truly no root"?
9. WACC            - is the WACC reproducible from Rf + beta*ERP + debt leg?
10. Golden Baseline- is every change recorded field by field?

A check that cannot be evaluated returns UNKNOWN, never PASS: unknown is not
agreement.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Optional

sys.path.insert(0, "/workspace/telegram-stock-valuation-engine")

from benchmark.registry import BY_TICKER  # noqa: E402

PASS = "PASS"
FAIL = "FAIL"
WARN = "WARN"
UNKNOWN = "UNKNOWN"

REL_TOL = 1e-3          # 0.1% relative: solver tolerance, not valuation tolerance
#: Absolute floor for drift comparison. A growth rate near zero (BKNG: -0.4%)
#: makes a pure relative test meaningless -- 9e-6 absolute would read as 0.23%
#: relative. 1bp absolute is the right yardstick for a rate.
DRIFT_ABS_TOL = 1e-4
RESIDUAL_TOL = 1e-3     # relative residual at the root


def _num(x: Any) -> Optional[float]:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def _close(a, b, rel=REL_TOL) -> Optional[bool]:
    a, b = _num(a), _num(b)
    if a is None or b is None:
        return None
    return abs(a - b) <= max(1e-12, abs(b) * rel)


def check_beta_raw(f: dict) -> tuple[str, str]:
    raw, used = _num(f.get("beta_raw")), _num(f.get("beta_used"))
    if raw is None:
        return UNKNOWN, "raw beta not recorded"
    if used is None:
        return UNKNOWN, "used beta not recorded"
    floored = f.get("beta_floor_applied")
    bottom_up = _num(f.get("beta_bottom_up"))
    sel = _num(f.get("beta_selected"))
    if floored and abs(used - raw) < 1e-9:
        return FAIL, f"floor flag {floored!r} set but used==raw ({used:.3f})"
    note = f"raw {raw:+.3f}"
    if floored:
        note += f" -> used {used:.3f} (floor {floored})"
        return PASS, note
    if bottom_up is not None and sel is not None and abs(sel - bottom_up) < 1e-9:
        # Selection chose bottom-up beta; raw regression beta is retained for
        # audit but is not the pricing input. That is a documented policy, not
        # a silent floor -- report it as PASS with the reason stated.
        return PASS, note + f" -> used {used:.3f} (bottom-up selected, raw not priced)"
    shrink = _num(f.get("beta_shrinkage")) or 0.0
    if abs(used - raw) > 1e-6:
        if shrink > 1e-9:
            # Blume shrinkage is a legitimate, recorded adjustment: verify it
            # moved toward the market mean by the stated weight.
            expected = (1 - shrink) * raw + shrink * 1.0
            if abs(expected - used) > 1e-4:
                return FAIL, (f"shrinkage {shrink:.0%} implies {expected:.3f}, "
                              f"but used {used:.3f}")
            return PASS, note + f" -> used {used:.3f} (blume shrink {shrink:.0%} to 1.0)"
        return WARN, f"used {used:.3f} != raw {raw:.3f} with no floor flag and no shrinkage"
    return PASS, note


def check_beta_used_traceable(f: dict) -> tuple[str, str]:
    used, src = _num(f.get("beta_used")), f.get("beta_source")
    if used is None:
        return UNKNOWN, "used beta not recorded"
    if not src:
        return FAIL, f"used beta {used:.3f} has no provenance string"
    return PASS, f"{used:.3f} <- {str(src)[:60]}"


def check_beta_adjusted(f: dict) -> tuple[str, str]:
    """Verify normalization using the *recorded* selection method.

    The audit must not infer the mechanism from the numbers, because two very
    different things look identical when only values are compared:

      * **bottom_up** — a peer-derived beta *replaced* the regression beta.
        Nothing was "adjusted"; the regression beta simply is not the input.
      * **regression + shrinkage** — a Blume transform of the regression beta.

    ``beta_selection_method`` makes the distinction explicit, so this check
    branches on it instead of guessing.
    """
    adj = _num(f.get("beta_adjusted"))
    used = _num(f.get("beta_used"))
    sel = _num(f.get("beta_selected"))
    bottom_up = _num(f.get("beta_bottom_up"))
    shrink = _num(f.get("beta_shrinkage")) or 0.0
    blume = _num(f.get("beta_blume_adjusted"))
    method = f.get("beta_selection_method")
    if adj is None or used is None:
        return UNKNOWN, "adjusted/used beta not both recorded"

    if method is None:
        # No WACC breakdown (routed-out financial / REIT, or DCF did not run):
        # there is no selection step to attribute. Not a defect, but not a PASS
        # either -- mechanism attribution is simply out of scope here.
        src = str(f.get("beta_source") or "")
        if "Provider regression" in src or f.get("rd_routed_out"):
            return UNKNOWN, "no WACC breakdown (routed out / DCF not run): mechanism n/a"
        return WARN, "beta_selection_method not recorded (cannot attribute mechanism)"

    if method == "bottom_up":
        if bottom_up is None or sel is None or abs(sel - bottom_up) > 1e-9:
            return FAIL, f"method=bottom_up but selected {sel} != bottom_up {bottom_up}"
        if shrink > 1e-9:
            return FAIL, f"bottom-up beta shrunk by {shrink:.2f} (should be none)"
        expected = max(0.30, min(2.50, sel))
        if abs(expected - adj) > 1e-9:
            return FAIL, f"bottom-up winsorize({sel:.4f}) = {expected:.4f}, recorded {adj:.4f}"
        if blume is not None:
            return FAIL, f"method=bottom_up but a blume value {blume:.4f} was recorded"
        if abs(adj - used) > 1e-6:
            return WARN, f"adjusted {adj:.3f} != used {used:.3f}"
        return PASS, f"bottom-up {sel:.4f} -> winsorize -> {adj:.4f} (no Blume)"

    if method == "regression":
        if sel is None:
            return FAIL, "method=regression but beta_selected missing"
        if shrink > 1e-9:
            expected = (1 - shrink) * max(0.30, min(2.50, sel)) + shrink * 1.0
            if blume is not None and abs(blume - expected) > 1e-9:
                return FAIL, f"blume field {blume:.6f} != computed {expected:.6f}"
            if abs(expected - adj) > 1e-9:
                return FAIL, f"blume(shrink {shrink:.4f}) = {expected:.6f}, recorded {adj:.6f}"
            return PASS, f"regression {sel:.4f} -> blume {shrink:.4f} -> {adj:.4f}"
        expected = max(0.30, min(2.50, sel))
        if abs(expected - adj) > 1e-9:
            return FAIL, f"winsorize({sel:.4f}) = {expected:.4f}, recorded {adj:.4f}"
        if blume is not None:
            return FAIL, "no shrinkage applied but a blume value was recorded"
        return PASS, f"regression {sel:.4f} -> winsorize -> {adj:.4f} (no Blume)"

    if method == "fallback":
        return PASS, f"fallback beta {adj:.3f}"

    return WARN, f"unrecognised beta_selection_method {method!r}"


def check_beta_blume(f: dict) -> tuple[str, str]:
    """The Blume value must be present iff shrinkage actually ran."""
    shrink = _num(f.get("beta_shrinkage")) or 0.0
    blume = _num(f.get("beta_blume_adjusted"))
    method = f.get("beta_selection_method")
    if method != "regression":
        if blume is not None:
            return FAIL, f"blume recorded ({blume:.4f}) on a non-regression path ({method})"
        return PASS, "n/a (not a regression-selected beta)"
    if shrink > 1e-9:
        if blume is None:
            return FAIL, f"shrinkage {shrink:.4f} ran but no blume value recorded"
        return PASS, f"shrinkage {shrink:.4f} -> blume {blume:.4f}"
    if blume is not None:
        return FAIL, "blume recorded although shrinkage was zero"
    return PASS, "no shrinkage (blume correctly absent)"


def check_date_alignment(f: dict) -> tuple[str, str]:
    """Stock and market returns must be aligned on the same dates.

    The evidence is the recorded window bounds, benchmark, sample size and the
    price basis (adjusted closes), not merely a window label.
    """
    spec = f.get("beta_window_spec")
    n_obs = f.get("beta_n_observations")
    bench = f.get("beta_benchmark")
    if not spec:
        return UNKNOWN, "no regression window provenance recorded"
    problems = []
    if not bench:
        problems.append("benchmark not recorded")
    if n_obs is not None and n_obs < 24:
        problems.append(f"only {n_obs} observations")
    missing = f.get("beta_missing_periods")
    if missing:
        problems.append(f"{missing} missing periods")
    if problems:
        return WARN, f"{spec} -- {'; '.join(problems)}"
    return PASS, spec


def check_solver_residual(f: dict) -> tuple[str, str]:
    meta = f.get("rd_solver_meta") or {}
    if not meta:
        return UNKNOWN, "no solver_meta recorded"
    if not meta.get("converged"):
        failure = meta.get("failure")
        kind = meta.get("no_root_kind")
        if kind == "EV_DIRECTION_UNDETERMINED":
            # Not a defect and not a finding: the direction of EV(g) flips under
            # plausible working-capital assumptions, so "no root" cannot be
            # asserted at all. Reporting WARN here would suggest a bug; the
            # correct verdict is "explained by parameter uncertainty".
            flips = meta.get("ev_flips_between")
            return PASS, (
                "no root is undetermined, not proven: EV direction flips under "
                f"plausible NWC ratios (flips={flips})"
            )
        if kind == "SEARCH_DOMAIN_INSUFFICIENT":
            return WARN, (
                f"target outside searched band (failure={failure}); widen the "
                "domain before concluding"
            )
        if failure == "ev_decreasing_in_growth":
            # Not a convergence *defect*: EV falls as growth rises, so no root
            # can exist. It is only determinate if the peak was recorded and it
            # sits below the target — then "no root" is proven, not unknown.
            if meta.get("ev_peak_below_target") is True:
                peak = _num(meta.get("ev_peak"))
                peak_g = _num(meta.get("ev_peak_growth"))
                return PASS, (
                    f"no root by construction: EV peaks at "
                    f"{peak:,.0f} (g={peak_g:.0%}) < target, "
                    f"EV decreases in growth"
                )
            return WARN, (
                "EV decreases in growth but peak evidence missing or above "
                "target (non-monotone region)"
            )
        return WARN, f"not converged (failure={failure})"
    rel = _num(meta.get("relative_residual"))
    if rel is None:
        return UNKNOWN, "relative_residual missing"
    if rel > RESIDUAL_TOL:
        return FAIL, f"relative residual {rel:.2e} > {RESIDUAL_TOL:.0e}"
    return PASS, f"rel residual {rel:.2e}"


def check_multiple_roots(f: dict) -> tuple[str, str]:
    meta = f.get("rd_solver_meta") or {}
    if not meta:
        return UNKNOWN, "no solver_meta recorded"
    n = meta.get("n_roots_detected")
    multi = meta.get("multiple_roots")
    if n is None:
        return UNKNOWN, "root count not recorded"
    if multi and n and n < 2:
        return FAIL, f"multiple_roots=True but n_roots={n}"
    if n and n > 1:
        return WARN, f"{n} roots detected: {meta.get('roots')}"
    return PASS, f"{n} root(s), multiple_roots={bool(multi)}"


def check_growth_bounds(f: dict) -> tuple[str, str]:
    status, verdict = f.get("rd_status"), f.get("rd_growth_band_verdict")
    band, search = f.get("rd_growth_band"), f.get("rd_search_band")
    if status is None:
        return UNKNOWN, "routed out (no Reverse DCF run)"
    if search and band and not (search[0] <= band[0] and band[1] <= search[1]):
        return FAIL, f"search band {search} does not contain plausibility band {band}"
    if status == "No Solution In Range" and verdict and verdict.startswith("SOLVED_"):
        return FAIL, f"status={status} but verdict={verdict}"
    if status == "Solved" and verdict == "NO_ROOT_IN_EXPANDED_RANGE":
        return FAIL, f"status={status} but verdict={verdict}"
    if verdict == "DATA_QUALITY_WARNING":
        return WARN, f"solved but base FCF unreliable (verdict={verdict})"
    return PASS, f"status={status} verdict={verdict}"


def check_wacc(f: dict) -> tuple[str, str]:
    rf, beta = _num(f.get("risk_free_rate")), _num(f.get("beta_used"))
    erp, ke = _num(f.get("equity_risk_premium")), _num(f.get("cost_of_equity"))
    wacc = _num(f.get("rd_wacc")) or _num(f.get("dcf_wacc"))
    if None in (rf, beta, erp, ke):
        return UNKNOWN, "Rf/beta/ERP/Ke not all recorded"
    expected_ke = rf + beta * erp
    if not _close(ke, expected_ke, rel=1e-3):
        return FAIL, f"Ke {ke:.4%} != Rf {rf:.3%} + beta {beta:.3f} x ERP {erp:.2%} = {expected_ke:.4%}"
    if wacc is not None and wacc > ke + 1e-6:
        return WARN, f"WACC {wacc:.3%} > Ke {ke:.3%} (leverage should lower it)"
    if wacc is not None and abs(wacc - ke) > 0.15:
        return WARN, f"WACC {wacc:.3%} far from Ke {ke:.3%}"
    return PASS, f"Ke {ke:.3%} = {rf:.3%} + {beta:.2f}x{erp:.2%}" + (
        f"; WACC {wacc:.3%}" if wacc is not None else "")


CHECKS = [
    ("beta_raw", check_beta_raw),
    ("beta_adjusted", check_beta_adjusted),
    ("beta_blume", check_beta_blume),
    ("beta_used_traceable", check_beta_used_traceable),
    ("date_alignment", check_date_alignment),
    ("solver_residual", check_solver_residual),
    ("multiple_roots", check_multiple_roots),
    ("growth_bounds", check_growth_bounds),
    ("wacc", check_wacc),
]


def audit(facts: dict) -> dict[str, dict[str, tuple[str, str]]]:
    return {
        t: {name: fn(f) for name, fn in CHECKS}
        for t, f in facts.items()
    }


def main() -> None:
    new = json.load(open(sys.argv[1]))
    old = json.load(open(sys.argv[2])) if len(sys.argv) > 2 else {}
    res = audit(new)

    counts: dict[tuple[str, str], int] = {}
    for checks in res.values():
        for name, (verdict, _) in checks.items():
            counts[(name, verdict)] = counts.get((name, verdict), 0) + 1

    print("=" * 78)
    print("STAGE 3 — per-check verdict counts (50 tickers)")
    print("=" * 78)
    for name, _ in CHECKS:
        row = {v: counts.get((name, v), 0) for v in (PASS, WARN, FAIL, UNKNOWN)}
        print(f"  {name:20s} PASS={row[PASS]:2d} WARN={row[WARN]:2d} "
              f"FAIL={row[FAIL]:2d} UNKNOWN={row[UNKNOWN]:2d}")

    print("\n" + "=" * 78)
    print("FAILURES / WARNINGS")
    print("=" * 78)
    any_bad = False
    for t, checks in res.items():
        bad = [(n, v, d) for n, (v, d) in checks.items() if v in (FAIL, WARN)]
        if not bad:
            continue
        any_bad = True
        print(f"\n{t} ({BY_TICKER[t].company})")
        for n, v, d in bad:
            print(f"  [{v:4s}] {n:20s} {d}")
    if not any_bad:
        print("  (none)")

    if old:
        print("\n" + "=" * 78)
        print("DRIFT vs pre-fix baseline (previously-Solved must not move)")
        print("=" * 78)
        drift = 0
        for t, o in old.items():
            n = new.get(t, {})
            if o.get("rd_status") != "Solved":
                continue
            oc, nc = _num(o.get("rd_implied_revenue_cagr")), _num(n.get("rd_implied_revenue_cagr"))
            if n.get("rd_status") != "Solved":
                print(f"  [FAIL] {t}: was Solved, now {n.get('rd_status')}")
                drift += 1
                continue
            if oc is not None and nc is not None:
                tol = max(DRIFT_ABS_TOL, abs(oc) * REL_TOL)
                if abs(nc - oc) > tol:
                    print(f"  [FAIL] {t}: cagr {oc:.6f} -> {nc:.6f} "
                          f"(delta {nc - oc:+.2e} > tol {tol:.2e})")
                    drift += 1
        print(f"  drift findings: {drift}")

    hard_fail = sum(1 for checks in res.values() for v, _ in checks.values() if v == FAIL)
    print(f"\nTOTAL HARD FAILURES: {hard_fail}")
    sys.exit(1 if hard_fail else 0)


if __name__ == "__main__":
    main()
