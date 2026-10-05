"""Bank dividend discount model."""
from __future__ import annotations

from typing import Any, List, Tuple

from config import ModelName, SolverStatus, get_logger
from data.models import FinancialData
from models.base import ValuationAssumption, ValuationModel, ValuationResult

log = get_logger("models.bank")


class BankDDMModel(ValuationModel):
    NAME = ModelName.BANK_DDM

    def __init__(self, risk_free: float = 0.04, market_premium: float = 0.06, beta: float = 1.0) -> None:
        super().__init__()
        self.risk_free = risk_free
        self.market_premium = market_premium
        self.beta = beta

    def applicability_check(self, data: FinancialData, profile: Any) -> Tuple[bool, List[str]]:
        reasons: List[str] = []
        if not profile or not getattr(profile, "is_financial_institution", False):
            reasons.append("Bank DDM is only for financial institutions")
        if data.ttm is None:
            reasons.append("TTM financials required")
        if data.market.current_price is None:
            reasons.append("Current price required")
        return (len(reasons) == 0, reasons)

    def calculate(self, data: FinancialData, profile: Any, **kwargs) -> ValuationResult:
        ttm = data.ttm
        shares = data.market.shares_outstanding or (ttm.shares_outstanding if ttm else None)
        if shares is None or shares <= 0:
            return ValuationResult(
                model_name=self.model_name,
                status=SolverStatus.INSUFFICIENT_DATA,
                notes=["Shares outstanding missing"],
                data_quality_score=data.quality.data_quality_score,
            )

        dividend = kwargs.get("dividend")
        if dividend is None:
            dividend = getattr(ttm, "dividend_per_share", None) if ttm else None
        if dividend is None:
            price = data.market.current_price or 0.0
            yield_value = data.market.dividend_yield or 0.02
            dividend = price * yield_value
        dividend = float(dividend)
        growth_1 = float(kwargs.get("growth_1", 0.08))
        growth_2 = float(kwargs.get("growth_2", 0.04))
        terminal_growth = float(kwargs.get("terminal_growth", 0.025))
        beta = float(kwargs.get("beta", self.beta))
        risk_free = float(kwargs.get("risk_free", self.risk_free))
        market_premium = float(kwargs.get("market_premium", self.market_premium))
        cost_of_equity = risk_free + beta * market_premium

        yr1 = dividend * (1 + growth_1)
        yr2 = yr1 * (1 + growth_1)
        yr3 = yr2 * (1 + growth_2)
        terminal_value = (yr3 * (1 + terminal_growth)) / (cost_of_equity - terminal_growth)
        pv = dividend / (1 + cost_of_equity) + yr1 / (1 + cost_of_equity) ** 2 + yr2 / (1 + cost_of_equity) ** 3
        pv += terminal_value / (1 + cost_of_equity) ** 3
        value_per_share = pv

        assumptions = [
            ValuationAssumption("Dividend", round(dividend, 4), "USD/share", "Current dividend"),
            ValuationAssumption("Cost of Equity", round(cost_of_equity, 4), "%", "CAPM estimate"),
            ValuationAssumption("Stage 1 Growth", round(growth_1, 4), "%", "Initial phase"),
            ValuationAssumption("Stage 2 Growth", round(growth_2, 4), "%", "Transition phase"),
            ValuationAssumption("Terminal Growth", round(terminal_growth, 4), "%", "Long-run growth"),
        ]
        notes = [
            f"Bank DDM price = ${value_per_share:,.2f}/share using CAPM cost of equity {cost_of_equity:.2%}",
            f"Dividend assumptions: {growth_1:.2%} -> {growth_2:.2%} -> {terminal_growth:.2%}",
        ]
        if data.market.current_price:
            spread = (value_per_share - data.market.current_price) / data.market.current_price
            notes.append(f"Price spread vs market: {spread:+.1%}")

        breakdown = {
            "dividend": dividend,
            "cost_of_equity": cost_of_equity,
            "growth_1": growth_1,
            "growth_2": growth_2,
            "terminal_growth": terminal_growth,
            "terminal_value": terminal_value,
            "pv_dividends": pv,
            "value_per_share": value_per_share,
            "shares_outstanding": shares,
        }

        return ValuationResult(
            model_name=self.model_name,
            status=SolverStatus.SOLVED,
            value_per_share=value_per_share,
            assumptions=assumptions,
            notes=notes,
            breakdown=breakdown,
            data_quality_score=data.quality.data_quality_score,
        )


__all__ = ["BankDDMModel"]
