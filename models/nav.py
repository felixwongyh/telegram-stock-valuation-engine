"""
models/nav.py - REIT NAV valuation model
"""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

from config import ModelName, SolverStatus, get_logger
from data.models import FinancialData
from models.base import ValuationAssumption, ValuationModel, ValuationResult

log = get_logger("models.nav")


class REITNAVModel(ValuationModel):
    NAME = ModelName.REIT_NAV

    def __init__(self, default_cap_rate: float = 0.055, affo_multiple: float = 15.0) -> None:
        super().__init__()
        self.default_cap_rate = default_cap_rate
        self.affo_multiple = affo_multiple

    def applicability_check(self, data: FinancialData, profile: Any) -> Tuple[bool, List[str]]:
        reasons: List[str] = []
        if not profile or not getattr(profile, "is_reit", False):
            reasons.append("REIT NAV is only for REITs")
        if data.ttm is None:
            reasons.append("TTM financials missing")
        shares = data.market.shares_outstanding or (data.ttm.shares_outstanding if data.ttm else None)
        if shares is None or shares <= 0:
            reasons.append("Shares outstanding required for NAV")
        if data.market.total_debt is None and data.market.net_debt is None:
            reasons.append("Debt level required for NAV")
        return (len(reasons) == 0, reasons)

    def calculate(self, data: FinancialData, profile: Any, **kwargs) -> ValuationResult:
        shares = data.market.shares_outstanding or (data.ttm.shares_outstanding if data.ttm else None)
        if shares is None or shares <= 0:
            return ValuationResult(
                model_name=self.model_name,
                status=SolverStatus.INSUFFICIENT_DATA,
                notes=["Shares outstanding missing"],
                data_quality_score=data.quality.data_quality_score,
            )

        ttm = data.ttm
        annuals = data.annual_income or []
        noi = kwargs.get("noi")
        if noi is None:
            candidates = []
            for s in annuals:
                if s.ebitda is not None:
                    candidates.append(float(s.ebitda))
                elif s.operating_income is not None:
                    candidates.append(float(s.operating_income))
            if ttm is not None:
                if ttm.ebitda is not None:
                    candidates.append(float(ttm.ebitda))
                elif ttm.operating_income is not None:
                    candidates.append(float(ttm.operating_income))
            if candidates:
                noi = max(candidates)
            else:
                noi = max((ttm.revenue or 0.0) * 0.60, 1.0)
        cap_rate = float(kwargs.get("cap_rate", self.default_cap_rate))
        if cap_rate <= 0:
            cap_rate = self.default_cap_rate

        prop_value = noi / cap_rate
        debt = float(data.market.total_debt or data.market.net_debt_or_zero() or 0.0)
        cash = float(data.market.cash_and_equivalents or 0.0)
        nav_value = prop_value - debt + cash
        nav_ps = nav_value / shares

        affo = kwargs.get("affo")
        if affo is None:
            affo = ttm.free_cash_flow if ttm and ttm.free_cash_flow is not None else (ttm.net_income if ttm and ttm.net_income is not None else noi * 0.65)
        affo_per_share = affo / shares if shares else 0.0
        affo_multiple = float(kwargs.get("affo_multiple", self.affo_multiple))
        affo_value_ps = affo_per_share * affo_multiple
        value_per_share = nav_ps

        cap_sens = []
        for delta in (-0.005, -0.0025, 0.0, 0.0025, 0.01):
            rate = max(0.01, cap_rate + delta)
            cap_sens.append((rate, (noi / rate - debt + cash) / shares))

        assumptions = [
            ValuationAssumption("NOI proxy", round(noi, 2), "USD", "TTM EBITDA / operating income proxy"),
            ValuationAssumption("Cap Rate", round(cap_rate, 4), "%", "Market cap-rate assumption"),
            ValuationAssumption("AFFO Multiple", round(affo_multiple, 2), "x", "P/AFFO anchor"),
            ValuationAssumption("Debt", round(debt, 2), "USD", "Total debt"),
            ValuationAssumption("Cash", round(cash, 2), "USD", "Cash & equivalents"),
        ]

        notes = [
            f"NAV per Share = (NOI / Cap Rate - Debt + Cash) / Shares = ${nav_ps:,.2f}",
            f"AFFO-based implied value = ${affo_value_ps:,.2f}/share at {affo_multiple:.2f}x P/AFFO",
        ]
        if data.market.current_price:
            price_gap = (nav_ps - data.market.current_price) / data.market.current_price
            notes.append(f"Current price vs NAV: {price_gap:+.1%}")

        breakdown = {
            "property_value": prop_value,
            "noi": noi,
            "cap_rate": cap_rate,
            "debt": debt,
            "cash": cash,
            "nav_value": nav_value,
            "nav_per_share": nav_ps,
            "affo_per_share": affo_per_share,
            "affo_value_per_share": affo_value_ps,
            "cap_rate_sensitivity": cap_sens,
            "shares_outstanding": shares,
            "value_per_share": value_per_share,
        }

        return ValuationResult(
            model_name=self.model_name,
            status=SolverStatus.SOLVED,
            value_per_share=value_per_share,
            enterprise_value=prop_value,
            equity_value=nav_value,
            assumptions=assumptions,
            notes=notes,
            breakdown=breakdown,
            data_quality_score=data.quality.data_quality_score,
        )


__all__ = ["REITNAVModel"]
