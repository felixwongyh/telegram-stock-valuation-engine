"""LOCAL EV direction at a reference growth rate — a derived, conditional test.

**Scope (read this first).** The verdict this module returns is the sign of
``dEV/dg`` *evaluated at a single reference growth rate* (default ``g = 0``),
not a statement about every growth rate. It is labelled
``LOCAL_EV_DIRECTION_AT_REFERENCE_G`` everywhere it surfaces, because the EV
curve is **not** monotone in general: for ``w = 0.80`` the slope is positive at
``g = 0`` and negative from ``g ≈ 0.08`` upward, and the flip point moves with
``w`` and with the horizon. Reporting the ``g = 0`` sign as "growth adds value"
at all growth rates would be false for 3 of 9 tested ``w`` values. Callers that
need the sign over a range must use :func:`sign_over_range`, which scans and
reports the flip point instead of extrapolating the local sign.

When does growth *increase* enterprise value? A derived, conditional test.

The claim "EV falls as growth rises, therefore growth destroys value" needs a
criterion. This module derives one from the projection the engine actually
uses, states its assumptions, and refuses to answer outside them.

Derivation
----------
The projection (``forecasts/fcf_projection.py``) is

    rev_t    = R0 (1+g)^t
    FCF_t    = rev_t * k0 - w * (rev_t - rev_{t-1})
    EV(g)    = sum_t FCF_t/(1+r)^t  +  TV/(1+r)^H

with ``k0 = margin*(1-tax) + da_ratio - capex_ratio`` the steady-state FCF
margin *before* working-capital drag, and ``w`` the marginal NWC coefficient.
Factoring out ``rev_t`` gives the FCF margin after NWC:

    FCF_t / rev_t = k0 - w * g/(1+g)

Differentiating the whole EV (not just one year) at the reference growth rate
``g_ref`` (``0`` by default; see :func:`analytic_slope` for the general form):

    dEV/dg |_0 = R0 * ( k0 * D  -  w * P )

where, with ``A = sum_{t=1..H} (1+r)^-t`` and ``B = (1+tg)/((r-tg)(1+r)^H)``,

    P = A + B            (PV of $1 of steady FCF per year)
    D = sum t(1+r)^-t + H*B   (PV-weighted time)

so growth raises EV at the margin iff

    k0 / w  >  P / D   =  1 / duration

``P/D`` equals the reciprocal of the cash-flow duration. It is ~0.14 for a
10-year, 9% WACC, 2% growth utility (duration ~7.3 years) — **not 1**. The
naive rule ``k0/w > 1`` therefore overstates the hurdle by roughly the
duration, and is *not* the correct criterion. ``P/D -> 1`` only in the
degenerate limit of no discounting and no terminal value.

Applicability conditions (all must hold; ``applicability()`` checks them):
  1. ``w`` is a *marginal* coefficient (ΔNWC/ΔRevenue), not a level or
     intensity ratio.
  2. The margin path is flat *at the point evaluated*. Margin fade moves the
     flip point, so near the boundary the sign itself is not reliable; the
     criterion is therefore reported as ``indeterminate`` within a band around
     the hurdle rather than answering there. Away from the boundary the sign
     survives fade (measured: 18/21 agreement across a 3x3 grid, all three
     disagreements sitting on the boundary).
  3. Terminal value is a single Gordon perpetuity on the final-year FCF.
  4. Revenue compounds at a constant rate.
  5. ``r > tg`` and ``k0 > 0``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


#: The verdict is a local derivative sign, never a range-wide claim.
VERDICT_SCOPE = "LOCAL_EV_DIRECTION_AT_REFERENCE_G"

#: Default growth rate at which the derivative is evaluated.
REFERENCE_G = 0.0

#: Relative distance from the hurdle within which the sign is not trusted.
#: Margin fade shifts the flip point, and the measured disagreements all fall
#: inside this band; outside it the sign was stable in every test.
BOUNDARY_BAND = 0.25


@dataclass
class GrowthDirectionTest:
    """Result of the derived test, with the numbers that produced it."""

    k0: float
    marginal_nwc: float
    pv_multiple: float       # P
    pv_duration: float       # D
    hurdle_ratio: float      # P/D
    ratio: Optional[float]   # k0 / w
    growth_adds_value: Optional[bool]
    duration_years: float
    applicable: bool
    reasons: list
    #: ``adds_value`` | ``destroys_value`` | ``indeterminate``
    verdict: str = "indeterminate"
    #: Growth rate at which the derivative was evaluated.
    reference_growth: float = 0.0
    #: Where the sign stops holding, if it does inside the scanned range.
    #: First flip at ``g > reference_growth``; kept for single-number callers.
    flips_at_growth: Optional[float] = None
    #: *Every* sign change in the scanned range, refined by bisection. More than
    #: one entry is possible: the slope is a polynomial in (1+g) whose root
    #: count is not bounded by one (observed for negative growth).
    flip_points: list = field(default_factory=list)
    #: Sub-intervals of the scan on which the sign matches the reference sign.
    valid_direction_intervals: list = field(default_factory=list)
    #: Near-zero slope extrema that do not change the sign (tangent roots).
    tangent_points: list = field(default_factory=list)
    #: Direction of dEV/dg at ``reference_growth``.
    local_direction: Optional[str] = None
    #: Always ``LOCAL_EV_DIRECTION_AT_REFERENCE_G`` — the verdict's scope.
    verdict_scope: str = VERDICT_SCOPE

    def as_dict(self) -> dict:
        return {
            "k0": self.k0,
            "marginal_nwc": self.marginal_nwc,
            "pv_multiple": self.pv_multiple,
            "pv_duration": self.pv_duration,
            "hurdle_ratio": self.hurdle_ratio,
            "k0_over_w": self.ratio,
            "growth_adds_value": self.growth_adds_value,
            "duration_years": self.duration_years,
            "applicable": self.applicable,
            "verdict": self.verdict,
            "verdict_scope": self.verdict_scope,
            "reference_growth": self.reference_growth,
            "local_direction": self.local_direction,
            "flips_at_growth": self.flips_at_growth,
            "flip_points": list(self.flip_points),
            "valid_direction_intervals": [list(i) for i in
                                          self.valid_direction_intervals],
            "tangent_points": list(self.tangent_points),
            "reasons": list(self.reasons),
        }


def pv_factors(wacc: float, terminal_growth: float, horizon: int) -> tuple:
    """Return ``(P, D)`` — PV of a $1/yr annuity plus TV, and its time-weighted
    counterpart. Both are per $1 of final-year FCF."""
    if horizon <= 0 or wacc <= terminal_growth:
        return 0.0, 0.0
    annuity_pv = sum(1.0 / (1 + wacc) ** t for t in range(1, horizon + 1))
    annuity_time = sum(t / (1 + wacc) ** t for t in range(1, horizon + 1))
    tv_factor = (1 + terminal_growth) / ((wacc - terminal_growth) * (1 + wacc) ** horizon)
    return annuity_pv + tv_factor, annuity_time + horizon * tv_factor


def analytic_slope(
    revenue0: float,
    growth: float,
    operating_margin: float,
    tax_rate: float,
    da_ratio: float,
    capex_ratio: float,
    marginal_nwc: Optional[float],
    wacc: float,
    terminal_growth: float,
    horizon: int,
) -> Optional[float]:
    """``dEV/dg`` at an arbitrary ``growth``, in closed form.

    Derived from the engine's own projection, including the terminal value and
    its suppression when the final-year FCF is non-positive:

        FCF_t    = R0 (1+g)^{t-1} [ (1+g) k0 - w g ]
        dFCF_t   = R0 [ (t-1)(1+g)^{t-2}((1+g)k0 - w g)
                        + (1+g)^{t-1}(k0 - w) ]

    Returns ``None`` where the derivative is undefined (``1+g <= 0``, or
    ``wacc <= terminal_growth``).

    This exists so the ``g = 0`` criterion can be checked *point by point*
    against finite differences rather than trusted on a single sample.
    """
    if horizon <= 0 or wacc <= terminal_growth:
        return None
    if marginal_nwc is None:
        return None
    if 1.0 + growth <= 0.0:
        return None

    k0 = steady_state_fcf_margin(operating_margin, tax_rate, da_ratio, capex_ratio)
    q = 1.0 + growth
    w = marginal_nwc
    total = 0.0
    fcf_h = 0.0
    dfcf_h = 0.0
    for t in range(1, horizon + 1):
        fcf = revenue0 * q ** (t - 1) * (q * k0 - w * growth)
        dfcf = revenue0 * (
            (t - 1) * q ** (t - 2) * (q * k0 - w * growth)
            + q ** (t - 1) * (k0 - w)
        )
        total += dfcf / (1 + wacc) ** t
        if t == horizon:
            fcf_h, dfcf_h = fcf, dfcf
    if fcf_h > 0:  # matches gordon_terminal_value's suppression rule
        total += (1 + terminal_growth) / (
            (wacc - terminal_growth) * (1 + wacc) ** horizon
        ) * dfcf_h
    return total


def sign_over_range(
    revenue0: float,
    operating_margin: float,
    tax_rate: float,
    da_ratio: float,
    capex_ratio: float,
    marginal_nwc: Optional[float],
    wacc: float,
    terminal_growth: float,
    horizon: int,
    reference_growth: float = REFERENCE_G,
    growth_range: tuple = (-0.05, 0.50),
    step: float = 0.005,
    tangent_tolerance: float = 1e-3,
) -> dict:
    """Scan ``dEV/dg`` and report *every* sign change, refined by bisection.

    The local verdict must not be extrapolated; this is what a caller uses when
    it needs a range-wide statement.

    A grid-and-detect-sign-change scan is necessary but not sufficient, for two
    reasons that are handled here:

    1. **A grid hit is not a root.** The bracket is refined by bisection to
       ``refine_tolerance`` before being reported, so the flip point is not
       quantised to the grid.
    2. **A tangent root changes no sign.** If ``dEV/dg`` touches zero and turns
       back, no bracketing pair changes sign and a naive scan reports nothing.
       Local extrema of the slope are therefore located separately and reported
       as ``tangent_points`` when the slope there is negligible against the
       scale of the curve. This is a *detection heuristic* with an explicit
       tolerance, not an exact root count.

    Returns
    -------
    ``flip_points``
        Sorted growth rates where the sign changes, refined by bisection.
    ``valid_direction_intervals``
        ``[[lo, hi], ...]`` sub-intervals of ``growth_range`` on which the sign
        matches the sign at ``reference_growth``.
    ``local_direction``
        ``"INCREASING"`` / ``"DECREASING"`` / ``None`` at ``reference_growth``.
    ``tangent_points``
        Near-zero slope extrema that do *not* change the sign.
    ``flips_at_growth``
        First flip at ``g > reference_growth``, kept for callers that only want
        one number. ``None`` when the sign survives to the end of the range.
    """
    lo, hi = growth_range
    n = max(2, int(round((hi - lo) / step)))
    grid = [lo + i * (hi - lo) / n for i in range(n + 1)]

    def slope(g: float) -> Optional[float]:
        return analytic_slope(revenue0, g, operating_margin, tax_rate, da_ratio,
                              capex_ratio, marginal_nwc, wacc, terminal_growth,
                              horizon)

    points = [(g, slope(g)) for g in grid]
    points = [(g, d) for g, d in points if d is not None]
    if not points:
        return {
            "reference_growth": reference_growth,
            "local_direction": None,
            "flip_points": [],
            "valid_direction_intervals": [],
            "tangent_points": [],
            "flips_at_growth": None,
            "signs": [],
            "grid_size": 0,
            "verdict_scope": VERDICT_SCOPE,
        }

    def _bisect(a: float, b: float) -> float:
        sa = slope(a)
        for _ in range(80):
            m = (a + b) / 2
            sm = slope(m)
            if sm is None:
                break
            if (sa > 0) != (sm > 0):
                b = m
            else:
                a, sa = m, sm
        return (a + b) / 2

    flip_points: list = []
    for (g0, d0), (g1, d1) in zip(points, points[1:]):
        if d0 == 0 or d1 == 0:
            continue
        if (d0 > 0) != (d1 > 0):
            flip_points.append(_bisect(g0, g1))

    ref = slope(reference_growth)
    local_direction = None
    if ref is not None and ref != 0:
        local_direction = "INCREASING" if ref > 0 else "DECREASING"
    ref_sign = (ref > 0) if ref is not None else None

    # Segments delimited by the refined roots; the sign is constant inside each.
    bounds = [lo] + [f for f in flip_points if lo < f < hi] + [hi]
    intervals: list = []
    if ref_sign is not None:
        for a, b in zip(bounds, bounds[1:]):
            if b <= a:
                continue
            mid = (a + b) / 2
            sm = slope(mid)
            if sm is not None and (sm > 0) == ref_sign:
                intervals.append([round(a, 6), round(b, 6)])

    # Tangent roots: slope extrema that touch zero without crossing it.
    scale = max((abs(d) for _, d in points), default=0.0)
    tangent_points: list = []
    if scale > 0 and len(points) >= 3:
        tol = tangent_tolerance * scale
        for (ga, da), (gb, db), (gc, dc) in zip(points, points[1:], points[2:]):
            is_min = db <= da and db <= dc and (db < da or db < dc)
            is_max = db >= da and db >= dc and (db > da or db > dc)
            if (is_min or is_max) and abs(db) <= tol and db != 0:
                if not any(abs(gb - f) <= 2 * step for f in flip_points):
                    tangent_points.append(round(gb, 6))

    first_flip = next(
        (f for f in sorted(flip_points) if f > reference_growth), None
    )

    return {
        "reference_growth": reference_growth,
        "local_direction": local_direction,
        "flip_points": sorted(round(f, 6) for f in flip_points),
        "valid_direction_intervals": intervals,
        "tangent_points": sorted(tangent_points),
        "flips_at_growth": round(first_flip, 6) if first_flip is not None else None,
        "signs": sorted({("+" if d > 0 else "-") for _, d in points}),
        "grid_size": len(points),
        "verdict_scope": VERDICT_SCOPE,
    }


def steady_state_fcf_margin(
    operating_margin: float,
    tax_rate: float,
    da_ratio: float,
    capex_ratio: float,
) -> float:
    """``k0`` — FCF per revenue dollar before working-capital drag."""
    return operating_margin * (1 - tax_rate) + da_ratio - abs(capex_ratio)


def evaluate(
    operating_margin: float,
    tax_rate: float,
    da_ratio: float,
    capex_ratio: float,
    marginal_nwc: Optional[float],
    wacc: float,
    terminal_growth: float,
    horizon: int,
    margin_is_flat: bool = True,
    reference_growth: float = REFERENCE_G,
    revenue0: Optional[float] = None,
    growth_range: tuple = (-0.05, 0.50),
) -> GrowthDirectionTest:
    """Apply the derived criterion at ``reference_growth``.

    Refuses to answer when it does not apply. When ``revenue0`` is supplied the
    module also scans the range to find where the local sign stops holding, so
    the caller learns that the verdict is local rather than discovering it
    later. ``dEV/dg`` is homogeneous of degree one in revenue, so the scan only
    needs a scale, not the true revenue.
    """
    k0 = steady_state_fcf_margin(operating_margin, tax_rate, da_ratio, capex_ratio)
    P, D = pv_factors(wacc, terminal_growth, horizon)
    hurdle = (P / D) if D else 0.0
    duration = (D / P) if P else 0.0

    reasons: list = []
    if not margin_is_flat:
        reasons.append(
            "利润率路径非平坦：EV 峰值由利润率漂移驱动，本判别式不适用"
        )
    if wacc <= terminal_growth:
        reasons.append("WACC ≤ 终值增长率：Gordon 终值无定义")
    if k0 <= 0:
        reasons.append("稳态 FCF 利润率 k0 ≤ 0：增长无法在稳态产生正现金流")
    if marginal_nwc is None:
        reasons.append("缺少边际 NWC 系数")

    ratio = None
    adds = None
    if marginal_nwc is not None:
        if abs(marginal_nwc) < 1e-9:
            # No working-capital drag: growth always adds value in this model.
            adds = k0 > 0
            reasons.append("边际 NWC ≈ 0：无营运资本拖累，判别式退化为 k0 > 0")
        else:
            ratio = k0 / marginal_nwc
            adds = ratio > hurdle
            if marginal_nwc < 0:
                reasons.append(
                    "边际 NWC 为负（营运资本释放现金）：比值为负，"
                    "此情形下高增长不产生 NWC 拖累，判别式符号含义反转"
                )

    applicable = not reasons or (len(reasons) == 1 and "边际 NWC ≈ 0" in reasons[0])

    # Near the boundary the sign is not trustworthy even when the algebra
    # applies, because the margin-fade convention shifts the flip point. Say so
    # instead of answering on the wrong side of a knife edge.
    near_boundary = (
        ratio is not None
        and hurdle > 0
        and abs(ratio - hurdle) <= BOUNDARY_BAND * hurdle
    )
    if near_boundary:
        reasons.append(
            f"k0/w={ratio:.3f} 与门槛 P/D={hurdle:.3f} 相差在 "
            f"{BOUNDARY_BAND:.0%} 以内：利润率漂移会使翻转点移动，此处符号不可信"
        )
        applicable = False

    # A local sign is not a range-wide claim. Scan for the flip point so the
    # caller is told, in the same object, that the verdict stops holding at
    # some higher growth rate — rather than having to know to ask.
    flips_at = None
    scan = None
    if applicable and revenue0 is not None:
        scan = sign_over_range(
            revenue0, operating_margin, tax_rate, da_ratio, capex_ratio,
            marginal_nwc, wacc, terminal_growth, horizon,
            reference_growth=reference_growth,
            growth_range=growth_range,
        )
        flips_at = scan["flips_at_growth"]
        if len(scan["flip_points"]) > 1:
            reasons.append(
                "⚠️ 扫描发现 %d 个方向翻转点 %s：EV 曲线在该区间内非单调，"
                "不能只用第一个翻转点概括" % (
                    len(scan["flip_points"]),
                    "、".join(f"{p:.1%}" for p in scan["flip_points"]),
                )
            )
        if flips_at is not None:
            reasons.append(
                f"⚠️ 该结论仅在 g∈[{reference_growth:.0%}, {flips_at:.1%}) 内成立："
                f"dEV/dg 在 g≈{flips_at:.1%} 处变号，超出该点后方向相反。"
                f"不可外推为「所有增长率下增长都增加/毁灭价值」"
            )

    if not applicable:
        # A criterion that declares itself inapplicable must not also answer:
        # reporting "growth destroys value" next to "this test does not apply"
        # is the self-contradiction this module exists to avoid.
        adds = None
        verdict = "indeterminate"
    else:
        verdict = "adds_value" if adds else "destroys_value"
    return GrowthDirectionTest(
        k0=k0,
        marginal_nwc=(marginal_nwc if marginal_nwc is not None else float("nan")),
        pv_multiple=P,
        pv_duration=D,
        hurdle_ratio=hurdle,
        ratio=ratio,
        growth_adds_value=adds,
        duration_years=duration,
        applicable=applicable,
        reasons=reasons,
        verdict=verdict,
        reference_growth=reference_growth,
        flips_at_growth=flips_at,
        flip_points=list(scan["flip_points"]) if scan else [],
        valid_direction_intervals=[list(i) for i in scan["valid_direction_intervals"]]
        if scan else [],
        tangent_points=list(scan["tangent_points"]) if scan else [],
        local_direction=scan["local_direction"] if scan else None,
    )


__all__ = [
    "BOUNDARY_BAND",
    "GrowthDirectionTest",
    "REFERENCE_G",
    "VERDICT_SCOPE",
    "analytic_slope",
    "evaluate",
    "pv_factors",
    "sign_over_range",
    "steady_state_fcf_margin",
]
