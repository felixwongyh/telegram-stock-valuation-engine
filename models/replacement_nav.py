"""
models/replacement_nav.py - Replacement-cost NAV valuation model

For a capital-intensive build-out whose cash-flow models break down (deeply
negative FCF / loss-making, e.g. an AI compute / GPU-infrastructure company
before it reaches steady state) a DCF is dominated by a terminal-value rescue
and a per-share earnings multiple is meaningless. The economically honest
anchor in that regime is the *asset base itself*: what would it cost to rebuild
the depreciable assets today?

    equity_value = book_equity + net_PP&E × (replacement_factor − 1)

i.e. the reported book equity uplifted by the difference between the
replacement cost of the depreciable asset base and its book carrying amount.
Only the depreciable (PP&E) portion is revalued; other net assets stay at book,
so the model does not double-count working capital or financial assets.

`net_PP&E` is reconstructed from the available history as
``Σ capex − Σ D&A`` (cumulative additions less cumulative depreciation). For a
young build-out with a short history this is a defensible proxy for the net
carrying amount of the compute/equipment base. When book equity is unavailable
the model falls back to ``replacement_PP&E − net debt``.

This is intentionally a *coverage* model: it keeps an asset-heavy pre-profit
name valued at 3-4 surviving models instead of leaning on a down-weighted DCF.
"""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

from config import ModelName, SolverStatus, get_logger
from data.models import FinancialData
from models.base import ValuationAssumption, ValuationModel, ValuationResult

log = get_logger("models.replacement_nav")


class ReplacementNAVModel(ValuationModel):
    """Asset-based (replacement-cost) NAV for capital-intensive build-outs."""

    NAME = ModelName.REPLACEMENT_NAV

    # Below this capex/revenue ratio the company is not capital-intensive enough
    # for an asset-based anchor to be relevant.
    MIN_CAPEX_RATIO: float = 0.30
    # Equipment replacement cost premium over net book carrying amount. Compute
    # hardware (GPU / datacenter) tends to be understated on the books relative
    # to its current replacement price.
    DEFAULT_REPLACEMENT_FACTOR: float = 1.15
    _SENSITIVITY_FACTORS: Tuple[float, ...] = (1.00, 1.10, 1.15, 1.25, 1.40)

    def __init__(self, replacement_factor: Optional[float] = None) -> None:
        super().__init__()
        self.replacement_factor = (
            float(replacement_factor)
            if replacement_factor is not None
            else self.DEFAULT_REPLACEMENT_FACTOR
        )

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _shares(data: FinancialData) -> Optional[float]:
        shares = data.market.shares_outstanding
        if shares is None and data.ttm is not None:
            shares = data.ttm.shares_outstanding
        return float(shares) if shares else None

    @staticmethod
    def _capex_ratio(data: FinancialData) -> Optional[float]:
        ttm = data.ttm
        if ttm is None or not ttm.revenue or ttm.revenue <= 0 or ttm.capex is None:
            return None
        return abs(float(ttm.capex)) / float(ttm.revenue)

    @staticmethod
    def _accumulated(data: FinancialData) -> Tuple[float, float]:
        """Return (Σ capex, Σ D&A) over the available annual history."""
        acc_capex = 0.0
        acc_da = 0.0
        for s in (data.annual_income or []):
            if s.capex is not None:
                acc_capex += abs(float(s.capex))
            if s.depreciation_amortization is not None:
                acc_da += abs(float(s.depreciation_amortization))
        return acc_capex, acc_da

    def _is_capital_intensive(self, data: FinancialData, profile: Any) -> bool:
        ci = getattr(profile, "capital_intensity", "Unknown") if profile else "Unknown"
        if ci in ("Very Capital Intensive", "Capital Intensive"):
            return True
        r = self._capex_ratio(data)
        return r is not None and r >= self.MIN_CAPEX_RATIO

    @staticmethod
    def _is_build_out(data: FinancialData, profile: Any) -> bool:
        """Pre-profit / high-growth asset build-out that cash-flow models mishandle."""
        ttm = data.ttm
        neg_fcf = bool(ttm and ttm.free_cash_flow is not None and ttm.free_cash_flow < 0)
        neg_ni = bool(ttm and ttm.net_income is not None and ttm.net_income < 0)
        high_growth = bool(profile and getattr(profile, "growth_profile", "") == "High Growth")
        return neg_fcf or neg_ni or high_growth

    # --------------------------------------------------------------- interface
    def applicability_check(
        self, data: FinancialData, profile: Any
    ) -> Tuple[bool, List[str]]:
        reasons: List[str] = []
        if profile is not None and getattr(profile, "is_financial_institution", False):
            reasons.append("Replacement NAV is not meaningful for financial institutions")
        if self._shares(data) is None:
            reasons.append("Shares outstanding required for Replacement NAV")
        if not self._is_capital_intensive(data, profile):
            reasons.append(
                "Replacement NAV requires a capital-intensive asset base "
                f"(capex/revenue ≥ {self.MIN_CAPEX_RATIO:.0%})"
            )
        acc_capex, acc_da = self._accumulated(data)
        if acc_capex - acc_da <= 0:
            reasons.append(
                "No net depreciable asset base reconstructable from capex history (Σ capex ≤ Σ D&A)"
            )
        if not self._is_build_out(data, profile):
            reasons.append(
                "Replacement NAV is for pre-profit / high-growth build-outs "
                "(cash-flow models remain the primary anchor here)"
            )
        return (len(reasons) == 0, reasons)

    def calculate(self, data: FinancialData, profile: Any, **kwargs) -> ValuationResult:
        shares = self._shares(data)
        if shares is None or shares <= 0:
            return ValuationResult(
                model_name=self.model_name,
                status=SolverStatus.INSUFFICIENT_DATA,
                notes=["Shares outstanding missing"],
                data_quality_score=data.quality.data_quality_score,
            )

        acc_capex, acc_da = self._accumulated(data)
        net_ppe = acc_capex - acc_da
        if net_ppe <= 0:
            return ValuationResult(
                model_name=self.model_name,
                status=SolverStatus.INSUFFICIENT_DATA,
                notes=[
                    f"Net depreciable asset base not reconstructable "
                    f"(Σ capex {acc_capex:,.0f} ≤ Σ D&A {acc_da:,.0f})"
                ],
                data_quality_score=data.quality.data_quality_score,
            )

        factor = float(kwargs.get("replacement_factor", self.replacement_factor))
        if factor <= 0:
            factor = self.DEFAULT_REPLACEMENT_FACTOR
        replacement_ppe = net_ppe * factor

        mkt = data.market
        debt = float(mkt.total_debt or 0.0)
        cash = float(mkt.cash_and_equivalents or 0.0)
        book_value = mkt.book_value

        if book_value is not None:
            # Uplift only the depreciable asset base; other net assets stay at book.
            equity_value = float(book_value) + net_ppe * (factor - 1.0)
            basis = "book equity + PP&E revaluation uplift"
        else:
            equity_value = replacement_ppe - debt + cash
            basis = "replacement PP&E − net debt"
        if equity_value <= 0:
            return ValuationResult(
                model_name=self.model_name,
                status=SolverStatus.INSUFFICIENT_DATA,
                notes=[
                    f"Replacement-cost equity value non-positive (${equity_value:,.0f}) — "
                    "asset base does not cover liabilities"
                ],
                data_quality_score=data.quality.data_quality_score,
            )

        value_per_share = equity_value / shares
        enterprise_value = equity_value + debt - cash

        sens = []
        for f in self._SENSITIVITY_FACTORS:
            if book_value is not None:
                ev = float(book_value) + net_ppe * (f - 1.0)
            else:
                ev = net_ppe * f - debt + cash
            if ev > 0:
                sens.append((round(f, 2), round(ev / shares, 2)))

        assumptions = [
            ValuationAssumption("Accumulated Capex", round(acc_capex, 2), "USD",
                                "Σ annual capital expenditure over available history"),
            ValuationAssumption("Accumulated D&A", round(acc_da, 2), "USD",
                                "Σ annual depreciation & amortisation"),
            ValuationAssumption("Net PP&E (proxy)", round(net_ppe, 2), "USD",
                                "Σ capex − Σ D&A"),
            ValuationAssumption("Replacement Factor", round(factor, 3), "x",
                                "Replacement-cost premium over net book PP&E"),
            ValuationAssumption("Debt", round(debt, 2), "USD", "Total debt"),
            ValuationAssumption("Cash", round(cash, 2), "USD", "Cash & equivalents"),
        ]

        notes = [
            f"Replacement NAV per Share = (equity base '{basis}') / shares = ${value_per_share:,.2f}",
            f"Net depreciable asset base ≈ ${net_ppe:,.0f} revalued at {factor:.2f}x → "
            f"${replacement_ppe:,.0f}",
        ]
        if mkt.current_price:
            gap = (value_per_share - mkt.current_price) / mkt.current_price
            notes.append(f"Current price vs Replacement NAV: {gap:+.1%}")
        notes.append(
            "资产基础法（重置成本）：不依赖 FCF/盈利，适用于重资本·高增长·亏损期的算力/设备建设期标的"
        )

        breakdown = {
            "accumulated_capex": acc_capex,
            "accumulated_da": acc_da,
            "net_ppe": net_ppe,
            "replacement_factor": factor,
            "replacement_ppe": replacement_ppe,
            "book_value": float(book_value) if book_value is not None else None,
            "basis": basis,
            "equity_value": equity_value,
            "enterprise_value": enterprise_value,
            "shares_outstanding": shares,
            "replacement_factor_sensitivity": sens,
            "value_per_share": value_per_share,
        }

        return ValuationResult(
            model_name=self.model_name,
            status=SolverStatus.SOLVED,
            value_per_share=value_per_share,
            enterprise_value=enterprise_value,
            equity_value=equity_value,
            assumptions=assumptions,
            notes=notes,
            breakdown=breakdown,
            data_quality_score=data.quality.data_quality_score,
        )


__all__ = ["ReplacementNAVModel"]
