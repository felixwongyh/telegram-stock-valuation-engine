"""
forecasts/nwc_utils.py - NWC ratios and forecast projection helpers.
"""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

from config import DEFAULT_NWC_CONFIG
from data.models import FinancialStatement
from data.nwc_utils import (
    capex_cash_outflow,
    effective_tax_rate,
    infer_change_in_nwc,
    nwc_from_cashflow_line,
    resolve_change_in_nwc,
)

DEFAULT_MARGINAL_NWC_RATIO = DEFAULT_NWC_CONFIG.default_marginal_ratio
DEFAULT_LEVEL_NWC_RATIO = DEFAULT_NWC_CONFIG.default_level_ratio


def level_nwc_to_revenue_ratio(annuals: List[FinancialStatement]) -> float:
    ratios: List[float] = []
    for s in annuals:
        nwc = resolve_change_in_nwc(s)
        if nwc is not None and s.revenue is not None and s.revenue > 0:
            ratios.append(nwc / s.revenue)
    if not ratios:
        return DEFAULT_LEVEL_NWC_RATIO
    return sum(ratios) / len(ratios)


def marginal_nwc_ratio(annuals: List[FinancialStatement]) -> Tuple[float, str]:
    """Marginal ΔNWC / ΔRevenue, estimated robustly.

    A plain mean of yearly ``ΔNWC / ΔRevenue`` ratios is dominated by years
    where revenue barely moved: the denominator shrinks, the ratio explodes, and
    a single such year can pin the estimate to the ±50% clamp (KO: ΔRev $0.9B
    vs ΔNWC $7.2B → ratio 8.2). Because ΔNWC is a *marginal* quantity, the
    robust estimator is the **aggregate** ratio over the whole window
    (ΣΔNWC / ΣΔRevenue) — the slope of a regression through the origin, which
    weights each year by how much revenue actually moved.

    When even the aggregate exceeds the clamp, the window is dominated by
    one-off working-capital swings (deferred revenue, supplier-term changes)
    rather than a sustainable marginal rate. Clamping silently would project
    "50% of every incremental revenue dollar is consumed by WC" forever, so we
    fall back to the average annual flow ratio (ΔNWC / revenue) — bounded and
    economically interpretable — and name that in the returned method.
    """
    if len(annuals) < 2:
        level = level_nwc_to_revenue_ratio(annuals)
        return _clamp_marginal(level), "level_fallback"

    sum_dnwc = 0.0
    sum_drev = 0.0
    for i in range(len(annuals) - 1):
        newer, older = annuals[i], annuals[i + 1]
        nwc = resolve_change_in_nwc(newer)
        if nwc is None or newer.revenue is None or older.revenue is None:
            continue
        delta_rev = newer.revenue - older.revenue
        # Ignore near-flat years: the ratio is noise-amplified and says nothing
        # about the marginal working-capital need per unit of growth.
        if newer.revenue > 0 and abs(delta_rev) < 0.01 * newer.revenue:
            continue
        if abs(delta_rev) < 1e-6:
            continue
        sum_dnwc += nwc
        sum_drev += delta_rev

    if abs(sum_drev) < 1e-6:
        level = level_nwc_to_revenue_ratio(annuals)
        return _clamp_marginal(level), "level_fallback"

    aggregate = sum_dnwc / sum_drev
    cfg = DEFAULT_NWC_CONFIG
    if not (cfg.marginal_clamp_min <= aggregate <= cfg.marginal_clamp_max):
        return _clamp_marginal(level_nwc_to_revenue_ratio(annuals)), "flow_fallback"
    return aggregate, "aggregate"


def forecast_nwc_change(delta_revenue: float, marginal_ratio: float) -> float:
    return marginal_ratio * delta_revenue


def business_type_from_profile(profile: Any) -> Optional[str]:
    if profile is None:
        return None
    bt = getattr(profile, "business_type", None)
    if bt is None:
        return None
    if isinstance(bt, str):
        return bt
    return getattr(bt, "value", str(bt))


def adjust_marginal_nwc_for_business_type(
    ratio: float, business_type: Optional[str]
) -> float:
    if not business_type:
        return ratio
    cfg = DEFAULT_NWC_CONFIG
    key = business_type.upper().replace(" ", "_")
    benchmarks = {
        "SAAS": cfg.benchmark_saas,
        "MATURE_TECH": cfg.benchmark_mature_tech,
        "REIT": cfg.benchmark_reit,
        "INDUSTRIAL": cfg.benchmark_industrial,
        "MANUFACTURING": cfg.benchmark_industrial,
    }
    if key not in benchmarks:
        return ratio
    bench = benchmarks[key]
    return cfg.industry_blend_historical * ratio + cfg.industry_blend_benchmark * bench


def _clamp_marginal(r: float) -> float:
    cfg = DEFAULT_NWC_CONFIG
    return max(cfg.marginal_clamp_min, min(cfg.marginal_clamp_max, r))


__all__ = [
    "DEFAULT_LEVEL_NWC_RATIO",
    "DEFAULT_MARGINAL_NWC_RATIO",
    "adjust_marginal_nwc_for_business_type",
    "business_type_from_profile",
    "capex_cash_outflow",
    "effective_tax_rate",
    "forecast_nwc_change",
    "infer_change_in_nwc",
    "level_nwc_to_revenue_ratio",
    "marginal_nwc_ratio",
    "nwc_from_cashflow_line",
    "resolve_change_in_nwc",
]
