"""
data/normalizer.py - Financial Data Normalization
- TTM calculations
- Unit consistency tracking
- Missing value marking
- Fiscal period alignment
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from config import get_logger
from data.models import DataQualityFlags, FinancialData, FinancialStatement
from data.nwc_utils import infer_change_in_nwc

log = get_logger("data.normalizer")


class FinancialNormalizer:
    """Normalizes raw financial data for valuation models."""

    @staticmethod
    def compute_ttm_from_quarters(q_stmts: List[FinancialStatement]) -> Optional[FinancialStatement]:
        """Compute Trailing-Twelve-Month from 4 latest quarterly statements."""
        if not q_stmts or len(q_stmts) < 4:
            return None
        last4 = q_stmts[:4]
        def _sum(attr: str) -> Optional[float]:
            vals = [getattr(s, attr) for s in last4]
            if all(v is None for v in vals):
                return None
            try:
                return sum(float(v) for v in vals if v is not None)
            except (ValueError, TypeError):
                return None
        def _avg(attr: str) -> Optional[float]:
            vals = [getattr(s, attr) for s in last4 if getattr(s, attr) is not None]
            if not vals:
                return None
            return sum(vals) / len(vals)
        ttm = FinancialStatement(
            period_end=f"TTM({last4[0].period_end})",
            period_type="ttm",
            currency=last4[0].currency,
            revenue=_sum("revenue"),
            gross_profit=_sum("gross_profit"),
            operating_income=_sum("operating_income"),
            ebit=_sum("ebit"),
            ebitda=_sum("ebitda"),
            net_income=_sum("net_income"),
            depreciation_amortization=_sum("depreciation_amortization"),
            capex=_sum("capex"),
            operating_cash_flow=_sum("operating_cash_flow"),
            free_cash_flow=_sum("free_cash_flow"),
            change_in_nwc=_sum("change_in_nwc"),
            interest_expense=_sum("interest_expense"),
            income_tax=_sum("income_tax"),
            shares_outstanding=last4[0].shares_outstanding,
            eps=_avg("eps"),
        )
        if ttm.revenue and ttm.gross_profit is None:
            pass
        return ttm

    @staticmethod
    def ensure_ttm(data: FinancialData) -> FinancialData:
        """Ensure TTM is populated. If missing, approximate from latest annual."""
        if data.ttm is None:
            if data.quarterly_income and len(data.quarterly_income) >= 4:
                data.ttm = FinancialNormalizer.compute_ttm_from_quarters(data.quarterly_income)
                data.notes.append("TTM computed from 4 most recent quarters.")
            elif data.annual_income:
                latest = data.annual_income[0]
                data.ttm = FinancialStatement(
                    period_end=f"TTM(approx from {latest.period_end})",
                    period_type="ttm",
                    currency=latest.currency,
                    revenue=latest.revenue,
                    gross_profit=latest.gross_profit,
                    operating_income=latest.operating_income,
                    ebit=latest.ebit,
                    ebitda=latest.ebitda,
                    net_income=latest.net_income,
                    depreciation_amortization=latest.depreciation_amortization,
                    capex=latest.capex,
                    operating_cash_flow=latest.operating_cash_flow,
                    free_cash_flow=latest.free_cash_flow,
                    change_in_nwc=latest.change_in_nwc,
                    interest_expense=latest.interest_expense,
                    income_tax=latest.income_tax,
                    shares_outstanding=latest.shares_outstanding,
                    eps=latest.eps,
                )
                data.notes.append("TTM approximated from latest annual report (not true TTM).")
        return data

    @staticmethod
    def fill_derived_fields(data: FinancialData) -> FinancialData:
        """Fill derived fields (gross profit from re-cogs, EBIT from OpInc, FCF from OCF-CapEx)."""
        all_stmts: List[FinancialStatement] = list(data.annual_income) + list(data.quarterly_income)
        if data.ttm is not None:
            all_stmts.append(data.ttm)
        for s in all_stmts:
            if s.revenue is not None and s.cost_of_revenue is not None and s.gross_profit is None:
                s.gross_profit = s.revenue - s.cost_of_revenue
            if s.revenue is not None and s.gross_profit is not None and s.cost_of_revenue is None:
                s.cost_of_revenue = s.revenue - s.gross_profit
            if s.operating_income is not None and s.ebit is None:
                s.ebit = s.operating_income
            if s.ebit is not None and s.depreciation_amortization is not None and s.ebitda is None:
                s.ebitda = s.ebit + s.depreciation_amortization
            if (s.operating_cash_flow is not None and s.capex is not None and s.free_cash_flow is None):
                s.free_cash_flow = s.operating_cash_flow + s.capex
            if s.change_in_nwc is None:
                inferred = infer_change_in_nwc(s)
                if inferred is not None:
                    s.change_in_nwc = inferred
            if (s.net_income is not None and s.shares_outstanding and s.shares_outstanding > 0
                    and s.eps is None):
                s.eps = s.net_income / s.shares_outstanding
        return data

    @staticmethod
    def normalize_all(data: FinancialData) -> FinancialData:
        """Full normalization pipeline."""
        data = FinancialNormalizer.ensure_ttm(data)
        data = FinancialNormalizer.fill_derived_fields(data)
        data = FinancialNormalizer._mark_missing(data)
        data = FinancialNormalizer._validate_currency_consistency(data)
        return data

    @staticmethod
    def _mark_missing(data: FinancialData) -> FinancialData:
        ttm = data.ttm
        if ttm is None:
            return data
        required = ["revenue", "operating_income", "ebit", "net_income",
                    "depreciation_amortization", "capex", "operating_cash_flow",
                    "free_cash_flow", "shares_outstanding"]
        for f in required:
            if getattr(ttm, f) is None:
                data.quality.missing_fields.append(f"ttm.{f}")
        n_years = len(data.annual_income)
        if n_years < 3:
            data.quality.data_quality_score -= 20
            data.quality.missing_fields.append(f"annual_income only {n_years}y (want ≥3y)")
        if data.market.current_price is None:
            data.quality.data_quality_score -= 20
        data.quality.data_quality_score = max(0, min(100, data.quality.data_quality_score))
        return data

    @staticmethod
    def _validate_currency_consistency(data: FinancialData) -> FinancialData:
        currencies = set()
        for s in data.annual_income:
            if s.currency:
                currencies.add(s.currency)
        for s in data.quarterly_income:
            if s.currency:
                currencies.add(s.currency)
        if data.ttm and data.ttm.currency:
            currencies.add(data.ttm.currency)
        if data.market.currency:
            currencies.add(data.market.currency)
        if len(currencies) > 1:
            data.quality.mixed_currencies = True
            data.quality.data_quality_score = max(0, data.quality.data_quality_score - 30)
            data.notes.append(f"WARNING: Mixed currencies detected: {currencies}")
        return data


__all__ = ["FinancialNormalizer"]
