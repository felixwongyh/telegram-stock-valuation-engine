"""
data/fcf_utils.py - Free cash flow resolution from statements.
"""
from __future__ import annotations

from typing import Optional, Tuple

from data.models import FinancialStatement


def resolve_ttm_fcf(stmt: FinancialStatement) -> Tuple[Optional[float], str]:
    """
    Resolve TTM/reference FCF without fabricating placeholders.

    Returns (value, source) where source is ``reported``, ``derived_ocf_capex``,
    or ``missing``.
    """
    if stmt.free_cash_flow is not None:
        return float(stmt.free_cash_flow), "reported"
    if stmt.operating_cash_flow is not None and stmt.capex is not None:
        return float(stmt.operating_cash_flow + stmt.capex), "derived_ocf_capex"
    return None, "missing"


__all__ = ["resolve_ttm_fcf"]
