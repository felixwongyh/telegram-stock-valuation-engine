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
    if len(annuals) < 2:
        level = level_nwc_to_revenue_ratio(annuals)
        return _clamp_marginal(level), "level_fallback"

    marginals: List[float] = []
    for i in range(len(annuals) - 1):
        newer, older = annuals[i], annuals[i + 1]
        nwc = resolve_change_in_nwc(newer)
        if nwc is None or newer.revenue is None or older.revenue is None:
            continue
        delta_rev = newer.revenue - older.revenue
        if abs(delta_rev) < 1e-6:
            continue
        marginals.append(nwc / delta_rev)

    if marginals:
        return _clamp_marginal(sum(marginals) / len(marginals)), "marginal"

    level = level_nwc_to_revenue_ratio(annuals)
    return _clamp_marginal(level), "level_fallback"


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
