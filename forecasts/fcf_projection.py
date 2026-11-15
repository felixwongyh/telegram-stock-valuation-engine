"""
forecasts/fcf_projection.py - Shared explicit-period FCF / DCF EV projection.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional

from data.models import FinancialData
from forecasts.forecast import ForecastEngine
from forecasts.nwc_utils import business_type_from_profile, forecast_nwc_change
from valuation.equity_bridge import enterprise_to_equity

# Unified floor for the Gordon-growth denominator spread (WACC − g). Terminal
# growth is already capped at WACC − 0.5% upstream, so this branch is a safety
# net only; the single constant replaces the previous inconsistent 1e-3 / 1e-4
# floors scattered across dcf.py / fcf_projection.py (Session #16).
MIN_WACC_TG_SPREAD: float = 0.005


@dataclass
class FcfProjectionResult:
    fcf_by_year: List[float]
    last_fcf: float
    pv_explicit: float
    pv_terminal: float
    enterprise_value: float
    # True when the terminal-year FCF is ≤ 0 and the terminal value was
    # suppressed (not sign-flipped). Callers must surface this explicitly.
    terminal_fcf_negative: bool = False


@dataclass
class TerminalValueResult:
    terminal_fcf: float
    terminal_value: float
    pv_terminal_value: float
    suppressed: bool
    inflated: bool
    note: Optional[str]


def gordon_terminal_value(
    last_fcf: Optional[float],
    wacc: float,
    terminal_growth: float,
    discount_years: int,
) -> TerminalValueResult:
    """Single, honest Gordon-growth terminal value used by every FCF model.

    Two defects this fixes (Session #16):

    1. **No silent sign flip.** The old code did
       ``if last_fcf <= 0: last_fcf = avg(abs(fcf_list))`` — a cash-burning
       terminal year was turned into a *positive* number and fed to Gordon
       growth, fabricating a positive terminal value for a company that never
       earns money. Here a non-positive terminal FCF suppresses the terminal
       value (0.0) and sets ``suppressed=True``; callers must mark the result
       APPROXIMATE / "turnaround assumption required" instead of quietly
       inventing value.
    2. **One consistent WACC − g guard.** ``spread <= 0`` uses a single floor
       (``MIN_WACC_TG_SPREAD``) and sets ``inflated=True`` so the caller can warn.
    """
    if last_fcf is None or last_fcf <= 0:
        return TerminalValueResult(
            terminal_fcf=last_fcf if last_fcf is not None else 0.0,
            terminal_value=0.0,
            pv_terminal_value=0.0,
            suppressed=True,
            inflated=False,
            note=(
                "终期 FCF ≤ 0：已抑制终值（不做符号翻转），仅保留显式期现值作为下限；"
                "该估值需明确转型（turnaround）假设才成立"
            ),
        )
    spread = wacc - terminal_growth
    inflated = spread <= 0
    if inflated:
        spread = MIN_WACC_TG_SPREAD
    tv = (last_fcf * (1 + terminal_growth)) / spread
    pv = tv / (1 + wacc) ** max(0, discount_years)
    return TerminalValueResult(
        terminal_fcf=last_fcf,
        terminal_value=tv,
        pv_terminal_value=pv,
        suppressed=False,
        inflated=inflated,
        note=(
            f"WACC ≤ 终值增长率：终值分母已用一致下限 {MIN_WACC_TG_SPREAD:.3%}（终值偏大，需谨慎）"
            if inflated
            else None
        ),
    )


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

    tv_res = gordon_terminal_value(last_fcf, wacc, terminal_growth, horizon)

    return FcfProjectionResult(
        fcf_by_year=fcf_list,
        last_fcf=last_fcf,
        pv_explicit=pv_explicit,
        pv_terminal=tv_res.pv_terminal_value,
        enterprise_value=pv_explicit + tv_res.pv_terminal_value,
        terminal_fcf_negative=tv_res.suppressed,
    )


def project_enterprise_value_flat_margin(
    base_revenue: float,
    revenue_cagr: float,
    fcf_margin: float,
    wacc: float,
    terminal_growth: float,
    horizon: int,
) -> FcfProjectionResult:
    """Project EV under a *flat* FCF/revenue margin (``FCF_t = revenue_t × fcf_margin``).

    Bypasses the operating-margin → NOPAT → D&A/CapEx/NWC bridge so that
    ``fcf_margin`` becomes a well-defined, independent solve target for the
    reverse-DCF "implied FCF margin" question (Phase 2, Session #17). Terminal
    value still routes through the single honest ``gordon_terminal_value`` guard.
    """
    pv_explicit = 0.0
    rev = base_revenue
    fcf_list: List[float] = []
    last_fcf = 0.0
    for _ in range(horizon):
        rev *= 1 + revenue_cagr
        fcf = rev * fcf_margin
        fcf_list.append(fcf)
        last_fcf = fcf

    for t, fcf in enumerate(fcf_list, start=1):
        pv_explicit += fcf / (1 + wacc) ** t

    tv_res = gordon_terminal_value(last_fcf, wacc, terminal_growth, horizon)
    return FcfProjectionResult(
        fcf_by_year=fcf_list,
        last_fcf=last_fcf,
        pv_explicit=pv_explicit,
        pv_terminal=tv_res.pv_terminal_value,
        enterprise_value=pv_explicit + tv_res.pv_terminal_value,
        terminal_fcf_negative=tv_res.suppressed,
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
    eq = enterprise_to_equity(proj.enterprise_value, data.market).equity_value
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
    "TerminalValueResult",
    "MIN_WACC_TG_SPREAD",
    "equity_value_per_share",
    "fcf_cagr_from_projection",
    "gordon_terminal_value",
    "project_enterprise_value",
    "project_enterprise_value_flat_margin",
    "project_enterprise_value_from_data",
]
