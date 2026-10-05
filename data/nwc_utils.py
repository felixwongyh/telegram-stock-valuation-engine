"""
data/nwc_utils.py - Working-capital fields on financial statements.

Convention: ``change_in_nwc`` is cash outflow from WC (positive = uses cash).
FCF: ``nopat + da - capex - change_in_nwc`` with ``capex`` negative (outflow).
"""
from __future__ import annotations

from typing import Optional

from config import DEFAULT_DCF_CONFIG
from data.models import FinancialStatement


def effective_tax_rate(
    stmt: FinancialStatement, default: Optional[float] = None
) -> float:
    if default is None:
        default = DEFAULT_DCF_CONFIG.tax_rate
    if (
        stmt.income_tax is not None
        and stmt.operating_income is not None
        and stmt.operating_income > 0
    ):
        tr = stmt.income_tax / stmt.operating_income
        if 0.0 <= tr <= 0.50:
            return tr
    return default


def capex_cash_outflow(stmt: FinancialStatement) -> Optional[float]:
    if stmt.capex is None:
        return None
    return -abs(float(stmt.capex))


def nwc_from_cashflow_line(cf_line_value: float) -> float:
    return -float(cf_line_value)


def infer_change_in_nwc(
    stmt: FinancialStatement, tax_rate: Optional[float] = None
) -> Optional[float]:
    tax = tax_rate if tax_rate is not None else effective_tax_rate(stmt)
    if stmt.operating_income is None or stmt.depreciation_amortization is None:
        return None
    capex = capex_cash_outflow(stmt)
    if capex is None or stmt.free_cash_flow is None:
        return None
    nopat = stmt.operating_income * (1 - tax)
    return nopat + stmt.depreciation_amortization + capex - stmt.free_cash_flow


def resolve_change_in_nwc(
    stmt: FinancialStatement, tax_rate: Optional[float] = None
) -> Optional[float]:
    if stmt.change_in_nwc is not None:
        return float(stmt.change_in_nwc)
    return infer_change_in_nwc(stmt, tax_rate)


__all__ = [
    "capex_cash_outflow",
    "effective_tax_rate",
    "infer_change_in_nwc",
    "nwc_from_cashflow_line",
    "resolve_change_in_nwc",
]
