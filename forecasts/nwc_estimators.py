"""Three economically distinct NWC measures — never interchange them.

The reverse-DCF growth model consumes exactly one of these:

    NWC_marginal = ΔNWC / ΔRevenue          (the model's coefficient)

The other two are *not* substitutes for it, and conflating them is the defect
this module exists to prevent:

    1. ``BalanceSheetNWCRatio``  = OperatingNWC / Revenue
       A *stock* ratio: how much working capital the business carries per
       revenue dollar. Dimensionless level, not a per-growth-dollar rate.

    2. ``NWCInvestmentIntensity`` = ΔNWC / Revenue
       A *flow* ratio per revenue dollar *of the whole business*. For NEE this
       is 1.9%. It is NOT ΔNWC/ΔRevenue; converting it needs a growth rate and
       the conversion is only an approximation.

    3. ``RobustMarginalNWC`` = ΔNWC / ΔRevenue
       The model coefficient, estimated from year-over-year *pairs* with a
       robust statistic (median / Theil-Sen / Huber) rather than from
       ΣΔNWC / ΣΔRevenue, whose denominator collapses when cumulative revenue
       growth is small (NEE: aggregate 24.9% vs annual-mean intensity 1.9%).

A ratio of the wrong dimension silently rescales the entire projection: using
1.9% where 24.9% is required understates working-capital drag by ~13x, and
using 24.9% where 1.9% is meant overstates it. Each estimator therefore carries
its own ``dimension`` label and callers must match on it.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Dimension labels. A consumer that needs a marginal coefficient must check
# ``dimension == DIM_MARGINAL``; nothing here will silently coerce.
# ---------------------------------------------------------------------------
DIM_LEVEL = "level"          # OperatingNWC / Revenue
DIM_INTENSITY = "intensity"  # ΔNWC / Revenue
DIM_MARGINAL = "marginal"    # ΔNWC / ΔRevenue

# Below this relative revenue move a year-over-year ratio is noise-dominated.
NEAR_ZERO_REV_MOVE = 0.01


@dataclass
class NWCEstimate:
    """One estimate, with everything needed to judge whether to trust it."""

    name: str
    dimension: str
    value: Optional[float]
    method: str
    n_observations: int = 0
    #: Per-year raw ratios, so a caller can see dispersion rather than a point.
    samples: List[float] = field(default_factory=list)
    #: Years dropped because |ΔRevenue| was too small to form a ratio.
    n_near_zero_rev: int = 0
    #: Revenue declines are legitimate but invert the sign of a marginal ratio;
    #: counting them lets a reader judge whether the median is dominated by them.
    n_revenue_decline: int = 0
    notes: List[str] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return self.value is not None

    @property
    def dispersion(self) -> Optional[float]:
        if len(self.samples) < 2:
            return None
        return max(self.samples) - min(self.samples)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "dimension": self.dimension,
            "value": self.value,
            "method": self.method,
            "n_observations": self.n_observations,
            "dispersion": self.dispersion,
            "n_near_zero_rev": self.n_near_zero_rev,
            "n_revenue_decline": self.n_revenue_decline,
            "samples": [round(s, 6) for s in self.samples],
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# 1. Balance-sheet level ratio
# ---------------------------------------------------------------------------
def operating_nwc_from_balance_sheet(
    record: Dict[str, Any],
) -> Tuple[Optional[float], List[str]]:
    """Operating NWC = (AR + Inventory + OtherCurrentAssets)
                     − (AP + DeferredRevenue + OtherCurrentLiabilities).

    Cash and debt are deliberately excluded: they are financing, not operating
    working capital, and including them would make the ratio move with treasury
    policy instead of with the business.
    """
    def _get(key: str) -> Optional[float]:
        v = record.get(key)
        return float(v) if isinstance(v, (int, float)) else None

    ar = _get("Accounts Receivable")
    inv = _get("Inventory")
    oca = _get("Other Current Assets")
    ap = _get("Accounts Payable")
    dr = _get("Current Deferred Revenue")
    ocl = _get("Other Current Liabilities")

    missing: List[str] = []
    if ar is None:
        missing.append("Accounts Receivable")
    if ap is None:
        missing.append("Accounts Payable")
    if missing:
        # AR and AP are the irreducible core; without both, operating NWC is
        # not measurable and inventing zeros would fabricate a level.
        return None, missing

    assets = (ar or 0.0) + (inv or 0.0) + (oca or 0.0)
    liabilities = (ap or 0.0) + (dr or 0.0) + (ocl or 0.0)
    return assets - liabilities, missing


def balance_sheet_nwc_ratio(
    bs_records: Sequence[Dict[str, Any]],
    revenue_by_period: Dict[str, float],
) -> NWCEstimate:
    """OperatingNWC / Revenue, averaged across periods that have both."""
    ratios: List[float] = []
    n_missing_core = 0
    for rec in bs_records:
        period = str(rec.get("period_end") or "")
        rev = revenue_by_period.get(period)
        nwc, missing = operating_nwc_from_balance_sheet(rec)
        if nwc is None:
            n_missing_core += 1
            continue
        if rev is None or rev <= 0:
            continue
        ratios.append(nwc / rev)

    notes: List[str] = []
    if n_missing_core:
        notes.append(f"{n_missing_core} period(s) lacked AR or AP")
    if len(ratios) < 3:
        notes.append(
            f"only {len(ratios)} usable period(s): a level ratio from fewer is "
            "indicative, not established"
        )
    return NWCEstimate(
        name="balance_sheet_level",
        dimension=DIM_LEVEL,
        value=(sum(ratios) / len(ratios)) if ratios else None,
        method="mean of (AR+Inv+OCA−AP−DefRev−OCL)/Revenue",
        n_observations=len(ratios),
        samples=ratios,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# 2. Historical investment intensity
# ---------------------------------------------------------------------------
def nwc_investment_intensity(
    change_in_nwc_by_period: Dict[str, float],
    revenue_by_period: Dict[str, float],
) -> NWCEstimate:
    """Mean of ΔNWC / Revenue — cash invested in working capital per revenue
    dollar. This is the *proxy* quantity; it is not the model coefficient."""
    ratios: List[float] = []
    for period, dnwc in change_in_nwc_by_period.items():
        rev = revenue_by_period.get(period)
        if rev is None or rev <= 0 or dnwc is None:
            continue
        ratios.append(dnwc / rev)
    return NWCEstimate(
        name="investment_intensity",
        dimension=DIM_INTENSITY,
        value=statistics.fmean(ratios) if ratios else None,
        method="mean of ΔNWC/Revenue",
        n_observations=len(ratios),
        samples=ratios,
    )


# ---------------------------------------------------------------------------
# 3. Robust marginal ratio
# ---------------------------------------------------------------------------
def _theil_sen(pairs: Sequence[Tuple[float, float]]) -> Optional[float]:
    """Median of pairwise slopes through the origin.

    Through the origin because a zero revenue change must imply zero marginal
    working-capital need by construction; a free intercept would let the fit
    absorb level effects that belong to the balance-sheet ratio instead.
    """
    if not pairs:
        return None
    slopes = [dnwc / drev for drev, dnwc in pairs if abs(drev) > 1e-9]
    return statistics.median(slopes) if slopes else None


def _huber(pairs: Sequence[Tuple[float, float]], k: float = 1.345,
           max_iter: int = 100, tol: float = 1e-10) -> Optional[float]:
    """Huber M-estimate of the through-origin slope (iteratively reweighted).

    A few years with outsized working-capital swings (deferred revenue, supplier
    terms) can dominate a least-squares slope; Huber bounds their influence
    without discarding them entirely.
    """
    if not pairs:
        return None
    beta = statistics.median([dnwc / drev for drev, dnwc in pairs if abs(drev) > 1e-9] or [0.0])
    for _ in range(max_iter):
        resid = [dnwc - beta * drev for drev, dnwc in pairs]
        scale = statistics.median([abs(r) for r in resid]) or 1.0
        if scale <= 0:
            break
        num = den = 0.0
        for (drev, dnwc), r in zip(pairs, resid):
            w = 1.0 if abs(r) <= k * scale else (k * scale) / abs(r)
            num += w * drev * dnwc
            den += w * drev * drev
        if abs(den) < 1e-15:
            return beta
        new_beta = num / den
        if abs(new_beta - beta) <= tol:
            beta = new_beta
            break
        beta = new_beta
    return beta


def robust_marginal_nwc(
    annual_series: Sequence[Tuple[str, float, float]],
) -> NWCEstimate:
    """ΔNWC / ΔRevenue from year-over-year pairs, robustly.

    ``annual_series`` is ordered newest-first ``(period, revenue, ΔNWC)``.

    Deliberately *not* ΣΔNWC/ΣΔRevenue: that aggregate's denominator is the
    cumulative revenue change, which shrinks toward zero when growth stalls and
    then amplifies whatever residual sits in the numerator. Pairwise ratios keep
    each year's own denominator, and a median/Huber statistic stops one extreme
    year from setting the coefficient.
    """
    pairs: List[Tuple[float, float]] = []
    ratios: List[float] = []
    n_near_zero = 0
    n_decline = 0
    for i in range(len(annual_series) - 1):
        _, rev_new, dnwc = annual_series[i]
        _, rev_old, _ = annual_series[i + 1]
        if rev_new is None or rev_old is None or dnwc is None:
            continue
        drev = rev_new - rev_old
        if rev_new > 0 and abs(drev) < NEAR_ZERO_REV_MOVE * rev_new:
            n_near_zero += 1
            continue
        if abs(drev) < 1e-6:
            n_near_zero += 1
            continue
        if drev < 0:
            n_decline += 1
        pairs.append((drev, dnwc))
        ratios.append(dnwc / drev)

    notes: List[str] = []
    if n_decline:
        notes.append(
            f"{n_decline} year(s) had declining revenue: the marginal ratio "
            "inverts sign there, so the median mixes two regimes"
        )
    if n_near_zero:
        notes.append(f"{n_near_zero} year(s) dropped for near-zero revenue move")
    if len(pairs) < 3:
        notes.append(
            f"only {len(pairs)} usable pair(s): below the 3-pair floor for a "
            "robust slope"
        )

    median = statistics.median(ratios) if ratios else None
    ts = _theil_sen(pairs)
    huber = _huber(pairs)
    # The three robust statistics agreeing is the evidence that the coefficient
    # is a property of the business rather than of one year's denominator.
    values = [v for v in (median, ts, huber) if v is not None]
    if len(values) >= 2:
        spread = max(values) - min(values)
        if spread > max(0.10, 0.5 * abs(statistics.median(values))):
            notes.append(
                f"median/Theil-Sen/Huber disagree (spread {spread:.2f}): "
                "the coefficient is not stable across robust estimators"
            )

    return NWCEstimate(
        name="robust_marginal",
        dimension=DIM_MARGINAL,
        value=median,
        method="median of ΔNWC/ΔRevenue over y/y pairs (Theil-Sen/Huber cross-check)",
        n_observations=len(pairs),
        samples=ratios,
        n_near_zero_rev=n_near_zero,
        n_revenue_decline=n_decline,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Cross-estimator reconciliation
# ---------------------------------------------------------------------------
#: Below this revenue growth the intensity→marginal conversion divides by a
#: near-zero denominator and stops carrying information (CEG at 1.5% growth
#: yields a 1598% "marginal ratio" from a 23.5% intensity).
MIN_GROWTH_FOR_PROXY = 0.02


def marginal_from_intensity(intensity: float, revenue_growth: float) -> Optional[float]:
    """Convert investment intensity to a marginal coefficient.

    Since ``intensity = ΔNWC/Revenue`` and ``marginal = ΔNWC/ΔRevenue``:

        marginal = intensity / (ΔRevenue/Revenue) = intensity / growth

    This is an *identity only when both ratios are computed on the same
    period's revenue and the same ΔNWC*. Applied to a multi-year mean it is an
    approximation, and it is undefined for non-positive growth. Callers must
    treat the result as a proxy with an explicit interval, never as the
    coefficient.

    Refuses below ``MIN_GROWTH_FOR_PROXY``: dividing a 20% intensity by a 1.5%
    growth rate produces a 1600% "marginal ratio" that is arithmetic, not
    economics, and would silently dominate any comparison it entered.
    """
    if intensity is None or revenue_growth is None:
        return None
    if revenue_growth < MIN_GROWTH_FOR_PROXY:
        return None
    return intensity / revenue_growth


def reconcile(
    level: NWCEstimate,
    intensity: NWCEstimate,
    robust: NWCEstimate,
    revenue_growth: Optional[float],
) -> Dict[str, Any]:
    """Decide which estimates are usable and whether they conflict."""
    proxy = marginal_from_intensity(intensity.value, revenue_growth)
    proxy_refused_reason = None
    if proxy is None and intensity.value is not None and revenue_growth is not None:
        if revenue_growth < MIN_GROWTH_FOR_PROXY:
            proxy_refused_reason = (
                f"增长率 {revenue_growth:.1%} < {MIN_GROWTH_FOR_PROXY:.0%}："
                "强度→边际换算的分母过小，换算结果不具经济含义，已拒绝"
            )
    marginal_estimates = {
        "robust_marginal": robust.value,
        "intensity_proxy": proxy,
    }
    usable = {k: v for k, v in marginal_estimates.items() if v is not None}

    conflict = False
    spread = None
    if len(usable) >= 2:
        vals = list(usable.values())
        spread = max(vals) - min(vals)
        # A sign disagreement is the severe case: the two methods imply
        # opposite economic mechanisms, not merely different magnitudes.
        signs = {v > 0 for v in vals}
        if len(signs) > 1:
            conflict = True
        elif spread > max(0.15, 0.75 * abs(statistics.median(vals))):
            conflict = True

    return {
        "level": level.as_dict(),
        "intensity": intensity.as_dict(),
        "robust_marginal": robust.as_dict(),
        "intensity_proxy_marginal": proxy,
        "intensity_proxy_refused_reason": proxy_refused_reason,
        "revenue_growth_used": revenue_growth,
        "marginal_spread": spread,
        "estimates_conflict": conflict,
        "usable_marginal_estimates": usable,
    }


__all__ = [
    "DIM_INTENSITY",
    "MIN_GROWTH_FOR_PROXY",
    "DIM_LEVEL",
    "DIM_MARGINAL",
    "NEAR_ZERO_REV_MOVE",
    "NWCEstimate",
    "balance_sheet_nwc_ratio",
    "marginal_from_intensity",
    "nwc_investment_intensity",
    "operating_nwc_from_balance_sheet",
    "reconcile",
    "robust_marginal_nwc",
]
