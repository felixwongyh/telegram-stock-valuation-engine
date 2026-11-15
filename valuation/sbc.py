"""valuation/sbc.py - Stock-Based Compensation (SBC) normalization.

SBC is a *non-cash* expense, so the cash-flow statement adds it back inside CFO:
a reported ``FCF = CFO − CapEx`` therefore treats SBC as free. But SBC is not
free to **shareholders** — it either dilutes them or is compensation that would
otherwise be paid in cash. Valuing an SBC-heavy name (software / AI / early-stage
growth) on the raw CFO−CapEx FCF silently overstates equity value.

This module performs the adjustment **once, in one explicit place**, so no model
both deducts SBC *and* charges a dilution penalty for the same grants — the
double-count the valuation review warned against.

Methods
-------
``expense`` (default)
    Treat SBC as a real economic cost and deduct it from FCF::

        adjusted_fcf = reported_fcf − sbc

    The share count is left unchanged (the cost is already charged on the cash
    line). This matches a forecast whose operating margin is built from
    *reported* operating income — which already contains SBC as an expense — so a
    TTM-FCF model and a margin-built DCF sit on one convention.
``dilution``
    Leave FCF intact (SBC stays a non-cash add-back) and instead scale the share
    count for future issuance. The value impact lands on the per-share
    denominator, never on FCF. Requires an explicit annual dilution rate; without
    one the module refuses to fabricate a number and falls back to ``expense``.
``none``
    Disable the adjustment; report the raw FCF and flag it as un-normalized.

``None`` SBC (field absent) is never treated as a silent zero-claim: the raw FCF
is returned with a note that the adjustment was not applied.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

DEFAULT_SBC_METHOD = "expense"
SBC_METHODS = ("expense", "dilution", "none")


def _per_share(fcf: float, shares: Optional[float]) -> Optional[float]:
    if not shares or shares <= 0:
        return None
    return fcf / shares


@dataclass
class SbcNormalization:
    """Result of one SBC adjustment, recording before/after FCF and per-share."""

    reported_fcf: float
    sbc: float
    method: str
    # Amount deducted from FCF (expense method; 0.0 otherwise).
    sbc_deduction: float
    adjusted_fcf: float
    # Multiplier applied to the share count (dilution method; 1.0 otherwise).
    share_dilution_factor: float
    shares_in: Optional[float]
    shares_adjusted: Optional[float]
    reported_fcf_per_share: Optional[float]
    adjusted_fcf_per_share: Optional[float]
    notes: List[str] = field(default_factory=list)

    @property
    def applied(self) -> bool:
        return self.sbc_deduction != 0.0 or self.share_dilution_factor != 1.0

    def itemized_note(self) -> str:
        """Compact audit trail of the adjustment."""
        if self.method == "expense" and self.sbc_deduction:
            base = (
                f"SBC 归一化[expense]: FCF {self.reported_fcf:,.0f} − SBC "
                f"{self.sbc:,.0f} = {self.adjusted_fcf:,.0f}"
            )
            if self.reported_fcf_per_share is not None:
                base += (
                    f"；每股 FCF {self.reported_fcf_per_share:.2f} → "
                    f"{self.adjusted_fcf_per_share:.2f}"
                )
            return base
        if self.method == "dilution" and self.share_dilution_factor != 1.0:
            return (
                f"SBC 归一化[dilution]: FCF 不变 {self.reported_fcf:,.0f}，股数 "
                f"{self.shares_in:,.0f} → {self.shares_adjusted:,.0f} "
                f"(×{self.share_dilution_factor:.3f})；每股 FCF "
                f"{self.reported_fcf_per_share:.2f} → {self.adjusted_fcf_per_share:.2f}"
            )
        return f"SBC 归一化未调整（method={self.method}, SBC={self.sbc:,.0f}）"

    def as_dict(self) -> dict:
        return {
            "method": self.method,
            "reported_fcf": self.reported_fcf,
            "sbc": self.sbc,
            "sbc_deduction": self.sbc_deduction,
            "adjusted_fcf": self.adjusted_fcf,
            "share_dilution_factor": self.share_dilution_factor,
            "reported_fcf_per_share": self.reported_fcf_per_share,
            "adjusted_fcf_per_share": self.adjusted_fcf_per_share,
            "applied": self.applied,
        }


def normalize_fcf_for_sbc(
    reported_fcf: Optional[float],
    sbc: Optional[float],
    *,
    method: str = DEFAULT_SBC_METHOD,
    shares: Optional[float] = None,
    sbc_dilution_rate: Optional[float] = None,
) -> SbcNormalization:
    """Apply a single, explicitly-chosen SBC adjustment to a reference FCF.

    Parameters
    ----------
    reported_fcf:
        The FCF as reported (CFO − CapEx), i.e. **SBC already added back**.
    sbc:
        Stock-based compensation for the same period (a positive expense). ``None``
        or ``0`` means "no adjustment" — never a fabricated cost.
    method:
        One of :data:`SBC_METHODS`. ``dilution`` without ``sbc_dilution_rate``
        falls back to ``expense``.
    shares:
        Share count, used only to record before/after per-share FCF.
    sbc_dilution_rate:
        Annual share-issuance fraction for the ``dilution`` method.
    """
    notes: List[str] = []
    rfcf = float(reported_fcf or 0.0)
    sbc_v = float(sbc or 0.0)
    shares_f = float(shares) if shares else None
    ps_in = _per_share(rfcf, shares_f)

    if method not in SBC_METHODS:
        notes.append(f"未知 SBC 方法 {method!r} → 回退 {DEFAULT_SBC_METHOD}")
        method = DEFAULT_SBC_METHOD

    if method == "none":
        notes.append("SBC 归一化已关闭（method='none'）→ FCF 未调整")
        return SbcNormalization(
            rfcf, sbc_v, "none", 0.0, rfcf, 1.0, shares_f, shares_f, ps_in, ps_in, notes
        )

    if sbc_v <= 0:
        notes.append("无 SBC 数据（缺失或为 0）→ FCF 无需调整，按原始值使用")
        return SbcNormalization(
            rfcf, sbc_v, method, 0.0, rfcf, 1.0, shares_f, shares_f, ps_in, ps_in, notes
        )

    if method == "dilution" and (sbc_dilution_rate is None or sbc_dilution_rate <= 0):
        notes.append("dilution 方法缺少年化稀释率 → 回退 expense 方法（不臆造稀释率）")
        method = "expense"

    if method == "dilution":
        factor = 1.0 + float(sbc_dilution_rate)
        shares_adj = shares_f * factor if shares_f else None
        notes.append(
            f"SBC[dilution]：股数 ×{factor:.3f}（年化稀释 {sbc_dilution_rate:.2%}），"
            f"FCF 保持不调整 → 不重复扣除 SBC"
        )
        return SbcNormalization(
            rfcf, sbc_v, "dilution", 0.0, rfcf, factor,
            shares_f, shares_adj, ps_in, _per_share(rfcf, shares_adj), notes,
        )

    # expense (default / fallback)
    adjusted = rfcf - sbc_v
    notes.append(
        f"SBC[expense]：将 SBC 视为经济成本，FCF {rfcf:,.0f} − SBC {sbc_v:,.0f} "
        f"= {adjusted:,.0f}（股数不变，故不额外计稀释）"
    )
    return SbcNormalization(
        rfcf, sbc_v, "expense", sbc_v, adjusted, 1.0,
        shares_f, shares_f, ps_in, _per_share(adjusted, shares_f), notes,
    )


__all__ = [
    "SbcNormalization",
    "normalize_fcf_for_sbc",
    "DEFAULT_SBC_METHOD",
    "SBC_METHODS",
]
