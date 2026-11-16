"""
data/fcf_utils.py - Free cash flow resolution from statements.

This module is the **single exit point** for a company's reference (TTM) free
cash flow. Since M-69 the SBC-normalization layer is applied here *once*
(:func:`resolve_ttm_fcf_normalized`), so every FCF consumer — reverse DCF,
multiples, diagnostics — shares ONE convention instead of each re-applying (or
forgetting) the adjustment. Applying it in several places is exactly how SBC
gets double-counted (deducted as an expense *and* charged as dilution).

``resolve_ttm_fcf`` remains the raw primitive (no SBC); use it only for
existence checks. :func:`resolve_ttm_fcf_normalized` is the value producer.
"""
from __future__ import annotations

from typing import Optional, Tuple

from data.models import FinancialStatement
from valuation.sbc import DEFAULT_SBC_METHOD, SbcNormalization, normalize_fcf_for_sbc


def resolve_ttm_fcf(stmt: FinancialStatement) -> Tuple[Optional[float], str]:
    """
    Resolve the *raw* TTM/reference FCF without fabricating placeholders.

    Returns (value, source) where source is ``reported``, ``derived_ocf_capex``,
    or ``missing``. SBC is *not* applied here — this is the un-normalized
    primitive; consume :func:`resolve_ttm_fcf_normalized` for the headline value.
    """
    if stmt.free_cash_flow is not None:
        return float(stmt.free_cash_flow), "reported"
    if stmt.operating_cash_flow is not None and stmt.capex is not None:
        return float(stmt.operating_cash_flow + stmt.capex), "derived_ocf_capex"
    return None, "missing"


def resolve_ttm_fcf_normalized(
    stmt: FinancialStatement,
    *,
    shares: Optional[float] = None,
    method: str = DEFAULT_SBC_METHOD,
) -> Tuple[Optional[float], str, SbcNormalization]:
    """SBC-normalized TTM FCF — the FCF **main-chain exit** (M-69).

    Applies :func:`valuation.sbc.normalize_fcf_for_sbc` exactly once so no
    downstream model both deducts SBC *and* charges a dilution penalty for the
    same grants. The returned ``source`` gains a ``+sbc_normalized`` suffix when
    the adjustment actually moved the value.

    A missing reference FCF is returned as ``(None, "missing", …)`` — the caller
    must emit Insufficient Data, never a fabricated zero.
    """
    raw, source = resolve_ttm_fcf(stmt)
    sbc_norm = normalize_fcf_for_sbc(
        raw,
        getattr(stmt, "stock_based_compensation", None),
        method=method,
        shares=shares,
    )
    if raw is None:
        return None, "missing", sbc_norm
    if sbc_norm.applied:
        return sbc_norm.adjusted_fcf, f"{source}+sbc_normalized", sbc_norm
    return raw, source, sbc_norm


__all__ = ["resolve_ttm_fcf", "resolve_ttm_fcf_normalized"]
