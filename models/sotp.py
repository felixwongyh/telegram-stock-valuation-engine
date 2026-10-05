"""SOTP valuation model for diversified businesses."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from config import ModelName, SolverStatus, get_logger
from data.models import FinancialData
from models.base import ValuationAssumption, ValuationModel, ValuationResult

log = get_logger("models.sotp")


class SOTPModel(ValuationModel):
    NAME = ModelName.SOTP

    def __init__(self, conglomerate_discount: float = 0.10) -> None:
        super().__init__()
        self.conglomerate_discount = conglomerate_discount

    def applicability_check(self, data: FinancialData, profile: Any) -> Tuple[bool, List[str]]:
        reasons: List[str] = []
        if not profile or getattr(profile, "business_type", None) not in {"Conglomerate", "Diversified"}:
            reasons.append("SOTP is intended for conglomerates/diversified groups")
        if data.ttm is None:
            reasons.append("TTM financials required")
        return (len(reasons) == 0, reasons)

    def calculate(self, data: FinancialData, profile: Any, **kwargs) -> ValuationResult:
        segments: Dict[str, float] = kwargs.get("segments", {})
        if not segments:
            segments = {
                "operating_business": float(data.ttm.revenue * 0.80 if data.ttm and data.ttm.revenue else 1000.0),
                "financial_assets": float(data.market.cash_and_equivalents or 0.0),
                "other_assets": float(data.market.total_debt * 0.10 if data.market and data.market.total_debt else 0.0),
            }

        values = {}
        total_ev = 0.0
        for name, value in segments.items():
            if value < 0:
                values[name] = value
            else:
                values[name] = float(value)
            total_ev += values[name]

        debt = float(data.market.total_debt or 0.0)
        cash = float(data.market.cash_and_equivalents or 0.0)
        equity_value = total_ev - debt + cash
        shares = data.market.shares_outstanding or (data.ttm.shares_outstanding if data.ttm else None)
        if shares is None or shares <= 0:
            return ValuationResult(
                model_name=self.model_name,
                status=SolverStatus.INSUFFICIENT_DATA,
                notes=["Shares outstanding missing"],
                data_quality_score=data.quality.data_quality_score,
            )

        discount = float(kwargs.get("conglomerate_discount", self.conglomerate_discount))
        value_per_share = (equity_value * (1 - discount)) / shares

        assumptions = [
            ValuationAssumption("Segments", round(total_ev, 2), "USD", "Sum of segment values"),
            ValuationAssumption("Debt", round(debt, 2), "USD", "Net debt adjustment"),
            ValuationAssumption("Cash", round(cash, 2), "USD", "Cash adjustment"),
            ValuationAssumption("Conglomerate Discount", round(discount, 4), "%", "Portfolio discount"),
        ]
        notes = [
            f"SOTP Equity Value = Segment EV - Debt + Cash = ${equity_value:,.2f}",
            f"After {discount:.1%} conglomerate discount, implied value is ${value_per_share:,.2f}/share",
        ]
        if data.market.current_price:
            spread = (value_per_share - data.market.current_price) / data.market.current_price
            notes.append(f"Price spread vs market: {spread:+.1%}")

        breakdown = {
            "segments": values,
            "total_segment_ev": total_ev,
            "debt": debt,
            "cash": cash,
            "equity_value": equity_value,
            "conglomerate_discount": discount,
            "value_per_share": value_per_share,
            "shares_outstanding": shares,
        }

        return ValuationResult(
            model_name=self.model_name,
            status=SolverStatus.SOLVED,
            value_per_share=value_per_share,
            enterprise_value=total_ev,
            equity_value=equity_value,
            assumptions=assumptions,
            notes=notes,
            breakdown=breakdown,
            data_quality_score=data.quality.data_quality_score,
        )


__all__ = ["SOTPModel"]
