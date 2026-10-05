"""
models/multiples.py - Relative Valuation Multiples: P/E, EV/EBITDA, EV/Sales, P/B, FCF Yield
"""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

from config import ModelName, SolverStatus, get_logger
from data.models import FinancialData
from models.base import ValuationAssumption, ValuationModel, ValuationResult

log = get_logger("models.multiples")


class MultiplesModel(ValuationModel):
    """Relative valuation using peer multiples (with sector defaults)."""

    DEFAULT_MULTIPLES: dict = {
        "P/E": {"default": 18.0, "low": 10.0, "high": 30.0},
        "EV/EBITDA": {"default": 12.0, "low": 5.0, "high": 22.0},
        "EV/Sales": {"default": 2.5, "low": 0.5, "high": 8.0},
        "P/B": {"default": 2.5, "low": 0.8, "high": 6.0},
        "FCF Yield": {"default": 0.04, "low": 0.02, "high": 0.08},
    }

    def __init__(self, multiple_name: str = "P/E") -> None:
        super().__init__(name=multiple_name)
        self.multiple_name = multiple_name

    def applicability_check(
        self, data: FinancialData, profile: Any
    ) -> Tuple[bool, List[str]]:
        reasons: List[str] = []
        ttm = data.ttm
        m = self.multiple_name
        if m == "P/E":
            if ttm is None or ttm.eps is None or ttm.eps <= 0:
                reasons.append("P/E requires positive EPS")
            mkt = data.market
            if mkt.shares_outstanding is None or mkt.shares_outstanding <= 0:
                reasons.append("Shares outstanding required for P/E")
        elif m == "EV/EBITDA":
            if ttm is None or ttm.ebitda is None or ttm.ebitda <= 0:
                reasons.append("EV/EBITDA requires positive EBITDA")
            if profile and getattr(profile, "is_financial_institution", False):
                reasons.append("EV/EBITDA not meaningful for banks/insurance")
        elif m == "EV/Sales":
            if ttm is None or ttm.revenue is None or ttm.revenue <= 0:
                reasons.append("EV/Sales requires positive revenue")
        elif m == "P/B":
            bvps = data.market.book_value_per_share
            if bvps is None or bvps <= 0:
                reasons.append("P/B requires positive book value per share")
        elif m == "FCF Yield":
            if ttm is None or ttm.free_cash_flow is None or ttm.free_cash_flow <= 0:
                reasons.append("FCF Yield requires positive FCF")
            if data.market.market_cap is None or data.market.market_cap <= 0:
                reasons.append("FCF Yield requires market cap")
        else:
            reasons.append(f"Unknown multiple: {m}")
        return (len(reasons) == 0, reasons)

    def calculate(
        self, data: FinancialData, profile: Any, **kwargs
    ) -> ValuationResult:
        m = self.multiple_name
        sector = data.market.sector or "Unknown"
        defaults = MultiplesModel.DEFAULT_MULTIPLES[m]

        multiple = kwargs.get("multiple") or self._extract_sector_multiple(data, m)
        if multiple is None:
            multiple = defaults["default"]

        assumptions = [
            ValuationAssumption("Multiple", round(multiple, 4), "x", f"Sector={sector}; default fallback"),
            ValuationAssumption("Multiple Low", defaults["low"], "x", "Range bound"),
            ValuationAssumption("Multiple High", defaults["high"], "x", "Range bound"),
        ]

        ttm = data.ttm
        mkt = data.market
        pps: Optional[float] = None
        ev: Optional[float] = None
        eq: Optional[float] = None
        breakdown: dict = {"multiple": multiple, "sector": sector}

        if m == "P/E":
            eps = ttm.eps
            if eps and eps > 0:
                pps = multiple * eps
                eq = pps * (mkt.shares_outstanding or 0)
                ev = eq + mkt.net_debt_or_zero()
        elif m == "EV/EBITDA":
            if ttm.ebitda and ttm.ebitda > 0:
                ev = multiple * ttm.ebitda
                eq = ev - mkt.net_debt_or_zero()
                shares = mkt.shares_outstanding or (ttm.shares_outstanding if ttm else None)
                if shares and shares > 0 and eq is not None:
                    pps = eq / shares
        elif m == "EV/Sales":
            if ttm.revenue and ttm.revenue > 0:
                ev = multiple * ttm.revenue
                eq = ev - mkt.net_debt_or_zero()
                shares = mkt.shares_outstanding or (ttm.shares_outstanding if ttm else None)
                if shares and shares > 0 and eq is not None:
                    pps = eq / shares
        elif m == "P/B":
            bvps = mkt.book_value_per_share
            if bvps and bvps > 0:
                pps = multiple * bvps
                eq = pps * (mkt.shares_outstanding or 0)
                ev = eq + mkt.net_debt_or_zero()
        elif m == "FCF Yield":
            if ttm.free_cash_flow and ttm.free_cash_flow > 0 and multiple > 0:
                eq = ttm.free_cash_flow / multiple
                shares = mkt.shares_outstanding or (ttm.shares_outstanding if ttm else None)
                if shares and shares > 0:
                    pps = eq / shares
                ev = eq + mkt.net_debt_or_zero()

        if pps is None:
            return ValuationResult(
                model_name=m,
                status=SolverStatus.INSUFFICIENT_DATA,
                notes=["Unable to compute value with current inputs"],
                assumptions=assumptions,
                breakdown=breakdown,
                data_quality_score=data.quality.data_quality_score,
            )

        breakdown.update({"enterprise_value": ev, "equity_value": eq, "value_per_share": pps})
        low_pps, high_pps = self._range(pps, multiple, defaults, m, ttm, mkt)
        breakdown["low_value_per_share"] = low_pps
        breakdown["high_value_per_share"] = high_pps
        notes = []
        if data.market.current_price:
            pct = (pps - data.market.current_price) / data.market.current_price
            notes.append(f"当前价格 vs 估值：{pct:+.1%}")
        return ValuationResult(
            model_name=m,
            status=SolverStatus.SOLVED,
            value_per_share=pps,
            enterprise_value=ev,
            equity_value=eq,
            assumptions=assumptions,
            notes=notes,
            breakdown=breakdown,
            data_quality_score=data.quality.data_quality_score,
        )

    def _extract_sector_multiple(self, data: FinancialData, m: str) -> Optional[float]:
        mkt = data.market
        ttm = data.ttm
        if m == "P/E" and mkt.trailing_pe and mkt.trailing_pe > 0:
            return mkt.trailing_pe
        if m == "EV/EBITDA" and mkt.ev_to_ebitda and mkt.ev_to_ebitda > 0:
            return mkt.ev_to_ebitda
        if m == "P/B" and mkt.price_to_book and mkt.price_to_book > 0:
            return mkt.price_to_book
        return None

    def _range(self, pps: float, multiple: float, defaults: dict, m: str, ttm, mkt) -> Tuple[float, float]:
        ratio_low = defaults["low"] / max(1e-9, defaults["default"])
        ratio_high = defaults["high"] / max(1e-9, defaults["default"])
        return pps * ratio_low, pps * ratio_high


class PEModel(MultiplesModel):
    NAME = ModelName.PE
    def __init__(self) -> None: super().__init__("P/E")

class EVEBITDAModel(MultiplesModel):
    NAME = ModelName.EV_EBITDA
    def __init__(self) -> None: super().__init__("EV/EBITDA")

class EVSalesModel(MultiplesModel):
    NAME = ModelName.EV_SALES
    def __init__(self) -> None: super().__init__("EV/Sales")

class PBModel(MultiplesModel):
    NAME = ModelName.PB
    def __init__(self) -> None: super().__init__("P/B")

class FCFYieldModel(MultiplesModel):
    NAME = ModelName.FCF_YIELD
    def __init__(self) -> None: super().__init__("FCF Yield")


__all__ = [
    "MultiplesModel",
    "PEModel",
    "EVEBITDAModel",
    "EVSalesModel",
    "PBModel",
    "FCFYieldModel",
]
