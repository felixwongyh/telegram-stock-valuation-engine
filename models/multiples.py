"""
models/multiples.py - Relative Valuation Multiples: P/E, EV/EBITDA, EV/Sales, P/B, FCF Yield

Peer/sector multiples must be supplied (kwargs) or looked up from a sector table.
Never use the subject company's own trailing PE / EV/EBITDA / P/B — that is a
tautology (multiple × own metric ≈ current price).
"""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

from config import ModelName, SolverStatus, get_logger
from data.models import FinancialData
from models.base import ValuationAssumption, ValuationModel, ValuationResult

log = get_logger("models.multiples")

# Coarse sector defaults (NOT the company's own trading multiple).
# Used only when Yahoo sector/industry is present. Missing comps → insufficient.
SECTOR_PEER_MULTIPLES: dict = {
    "P/E": {
        "Technology": 22.0, "Consumer Cyclical": 16.0, "Industrials": 16.0,
        "Communication Services": 18.0, "Healthcare": 20.0, "Consumer Defensive": 18.0,
        "Energy": 12.0, "Basic Materials": 14.0, "Utilities": 16.0,
        "Financial Services": 12.0, "Real Estate": 18.0,
    },
    "EV/EBITDA": {
        "Technology": 14.0, "Consumer Cyclical": 10.0, "Industrials": 10.0,
        "Communication Services": 11.0, "Healthcare": 13.0, "Consumer Defensive": 11.0,
        "Energy": 6.0, "Basic Materials": 8.0, "Utilities": 10.0,
        "Real Estate": 16.0,
    },
    "EV/Sales": {
        "Technology": 4.0, "Consumer Cyclical": 1.2, "Industrials": 1.2,
        "Communication Services": 2.5, "Healthcare": 3.0, "Consumer Defensive": 1.5,
        "Energy": 1.5, "Basic Materials": 1.5, "Utilities": 3.0,
        "Real Estate": 8.0,
    },
    "P/B": {
        "Technology": 6.0, "Consumer Cyclical": 2.5, "Industrials": 3.0,
        "Communication Services": 3.0, "Healthcare": 4.0, "Consumer Defensive": 3.5,
        "Energy": 1.8, "Basic Materials": 2.0, "Utilities": 1.8,
        "Financial Services": 1.2, "Real Estate": 1.5, "Banks": 1.2,
    },
    "FCF Yield": {
        "Technology": 0.035, "Consumer Cyclical": 0.05, "Industrials": 0.05,
        "Communication Services": 0.04, "Healthcare": 0.04, "Consumer Defensive": 0.04,
        "Energy": 0.07, "Basic Materials": 0.06, "Utilities": 0.05,
        "Real Estate": 0.05,
    },
}


class MultiplesModel(ValuationModel):
    """Relative valuation using peer multiples (sector table or explicit kwargs)."""

    RANGE_BOUNDS: dict = {
        "P/E": {"low": 10.0, "high": 30.0},
        "EV/EBITDA": {"low": 5.0, "high": 22.0},
        "EV/Sales": {"low": 0.5, "high": 8.0},
        "P/B": {"low": 0.8, "high": 6.0},
        "FCF Yield": {"low": 0.02, "high": 0.08},
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
        sector = data.market.sector or ""
        industry = data.market.industry or ""
        bounds = MultiplesModel.RANGE_BOUNDS[m]

        multiple = kwargs.get("multiple")
        multiple_src = "explicit kwargs"
        if multiple is None:
            multiple, multiple_src = self._sector_peer_multiple(data, m, profile)

        if multiple is None:
            return ValuationResult(
                model_name=m,
                status=SolverStatus.INSUFFICIENT_DATA,
                notes=[
                    "No peer/sector multiple available (will not use the company's own "
                    f"trading {m} or a silent global default)"
                ],
                assumptions=[],
                breakdown={"sector": sector or "Unknown", "industry": industry or "Unknown"},
                data_quality_score=data.quality.data_quality_score,
            )

        assumptions = [
            ValuationAssumption("Multiple", round(multiple, 4), "x", multiple_src),
            ValuationAssumption("Multiple Low", bounds["low"], "x", "Range bound"),
            ValuationAssumption("Multiple High", bounds["high"], "x", "Range bound"),
        ]

        ttm = data.ttm
        mkt = data.market
        pps: Optional[float] = None
        ev: Optional[float] = None
        eq: Optional[float] = None
        breakdown: dict = {
            "multiple": multiple,
            "multiple_source": multiple_src,
            "sector": sector or "Unknown",
            "used_own_multiple": False,
        }

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
        low_pps, high_pps = self._range(pps, bounds)
        breakdown["low_value_per_share"] = low_pps
        breakdown["high_value_per_share"] = high_pps
        notes = [f"Peer/sector {m} = {multiple:g} ({multiple_src})"]
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

    _BT_TO_SECTOR = {
        "MatureTech": "Technology",
        "SaaS": "Technology",
        "Semiconductor": "Technology",
        "ConsumerCyclical": "Consumer Cyclical",
        "REIT": "Real Estate",
        "Bank": "Financial Services",
        "Insurance": "Financial Services",
        "Commodity": "Energy",
        "Utilities": "Utilities",
        "Conglomerate": "Industrials",
    }

    def _sector_peer_multiple(
        self, data: FinancialData, m: str, profile: Any = None
    ) -> Tuple[Optional[float], str]:
        table = SECTOR_PEER_MULTIPLES.get(m) or {}
        sector = (data.market.sector or "").strip()
        industry = (data.market.industry or "").strip()
        hay = f"{sector} {industry}".lower()
        if sector in table:
            return float(table[sector]), f"sector table[{sector}]"
        if hay.strip():
            for key, val in table.items():
                if key.lower() in hay:
                    return float(val), f"sector table[{key}] matched '{sector or industry}'"
        bt = getattr(profile, "business_type", None) if profile else None
        if bt and bt != "Unknown":
            mapped = self._BT_TO_SECTOR.get(bt)
            if mapped and mapped in table:
                return float(table[mapped]), f"classified type {bt} → sector table[{mapped}]"
        return None, "no sector table match"

    def _range(self, pps: float, bounds: dict) -> Tuple[float, float]:
        mid = (bounds["low"] + bounds["high"]) / 2.0
        ratio_low = bounds["low"] / max(1e-9, mid)
        ratio_high = bounds["high"] / max(1e-9, mid)
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
    "SECTOR_PEER_MULTIPLES",
]
