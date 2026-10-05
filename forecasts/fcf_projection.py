"""
forecasts/fcf_projection.py - Shared explicit-period FCF / DCF EV projection.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional

from data.models import FinancialData
from forecasts.forecast import ForecastEngine
from forecasts.nwc_utils import business_type_from_profile, forecast_nwc_change


@dataclass
class FcfProjectionResult:
    fcf_by_year: List[float]
    last_fcf: float
    pv_explicit: float
    pv_terminal: float
    enterprise_value: float


def project_enterprise_value(
    base_revenue: float,
    revenue_cagr: float,
    operating_margin: float,
    tax_rate: float,
    da_ratio: float,
    capex_ratio: float,
    nwc_marginal_ratio: float,
    wacc: float,
    terminal_growth: float,
    horizon: int,
) -> FcfProjectionResult:
    capex_ratio = abs(capex_ratio)
    pv_explicit = 0.0
    rev = base_revenue
    fcf_list: List[float] = []
    last_fcf = 0.0

    for _ in range(horizon):
        prev_rev = rev
        rev *= 1 + revenue_cagr
        op = rev * operating_margin
        nopat = op * (1 - tax_rate)
        da = rev * da_ratio
        capex = rev * capex_ratio
        nwc = forecast_nwc_change(rev - prev_rev, nwc_marginal_ratio)
        fcf = nopat + da - capex - nwc
        fcf_list.append(fcf)
        last_fcf = fcf

    for t, fcf in enumerate(fcf_list, start=1):
        pv_explicit += fcf / (1 + wacc) ** t

    if last_fcf <= 0:
        avg_abs = sum(abs(f) for f in fcf_list) / max(1, len(fcf_list))
        if avg_abs > 0:
            last_fcf = avg_abs

    if wacc > terminal_growth:
        tv = (last_fcf * (1 + terminal_growth)) / (wacc - terminal_growth)
    else:
        tv = (last_fcf * (1 + terminal_growth)) / max(1e-3, wacc - terminal_growth + 1e-3)
    pv_terminal = tv / (1 + wacc) ** horizon

    return FcfProjectionResult(
        fcf_by_year=fcf_list,
        last_fcf=last_fcf,
        pv_explicit=pv_explicit,
        pv_terminal=pv_terminal,
        enterprise_value=pv_explicit + pv_terminal,
    )


def project_enterprise_value_from_data(
    data: FinancialData,
    profile: Any,
    revenue_cagr: float,
    operating_margin: Optional[float],
    wacc: float,
    terminal_growth: float,
    horizon: int,
) -> Optional[FcfProjectionResult]:
    ttm = data.ttm
    if ttm is None or ttm.revenue is None or ttm.revenue <= 0:
        return None
    eng = ForecastEngine(
        horizon_years=horizon,
        business_type=business_type_from_profile(profile),
    )
    _, _, hist_om, da_ratio, capex_ratio, nwc_ratio, tax_rate = eng._extract_history(data)
    om = operating_margin if operating_margin is not None else hist_om
    return project_enterprise_value(
        ttm.revenue,
        revenue_cagr,
        om,
        tax_rate,
        da_ratio,
        capex_ratio,
        nwc_ratio,
        wacc,
        terminal_growth,
        horizon,
    )


def equity_value_per_share(
    data: FinancialData,
    profile: Any,
    revenue_cagr: float,
    operating_margin: Optional[float],
    wacc: float,
    terminal_growth: float,
    horizon: int,
) -> Optional[float]:
    ttm = data.ttm
    if ttm is None or ttm.shares_outstanding is None or ttm.shares_outstanding <= 0:
        return None
    proj = project_enterprise_value_from_data(
        data, profile, revenue_cagr, operating_margin, wacc, terminal_growth, horizon
    )
    if proj is None:
        return None
    eq = proj.enterprise_value - data.market.net_debt_or_zero()
    return eq / ttm.shares_outstanding


def fcf_cagr_from_projection(fcf_list: List[float], horizon: int) -> Optional[float]:
    if not fcf_list or horizon < 1:
        return None
    start = fcf_list[0]
    end = fcf_list[-1]
    if start is None or end is None or start <= 0 or end <= 0:
        return None
    return (end / start) ** (1 / horizon) - 1


__all__ = [
    "FcfProjectionResult",
    "equity_value_per_share",
    "fcf_cagr_from_projection",
    "project_enterprise_value",
    "project_enterprise_value_from_data",
]
