"""valuation/equity_bridge.py - Enterprise Value ↔ Equity Value bridge.

Every EV-based model (DCF, Reverse DCF, Multiples, SOTP, Unit-Economics) used to
compute ``equity = ev - net_debt`` inline. That identity is exact only for a
simple capital structure. A company with minority interests, preferred equity,
associate / JV investments held outside the operating FCF, or IFRS-16 leases
needs an explicit, auditable bridge:

    Equity = EV − NetDebt − MinorityInterest − PreferredEquity
             − Leases(if not already in debt) − OtherClaims + NonOperatingAssets

Design rules (Phase 1 — Valuation Integrity):

* Every term is optional; ``None`` means "no such claim on file" — never a
  silent zero that would double-count or under-count a claim.
* **No double-deduction.** When the provider's ``total_debt`` already includes
  lease liabilities (``leases_in_debt is True``) the bridge does not deduct them
  again. When minority interest / preferred equity is already inside
  ``net_debt``, the caller declares it via the ``net_debt_includes_*`` flags.
* Both directions share one adjustment resolver, so ``equity_to_enterprise`` is
  the exact inverse of ``enterprise_to_equity`` (no drift between models).
* The bridge returns the equity value **and** the itemised adjustments + notes,
  so a report can show its work and a reviewer can audit each step.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from data.models import MarketData


@dataclass
class EquityBridge:
    """An itemised EV → Equity bridge. All amounts in the reporting currency."""

    enterprise_value: float
    net_debt: float
    minority_interest: float
    preferred_equity: float
    lease_liabilities: float
    other_claims: float
    non_operating_assets: float
    equity_value: float
    leases_in_debt: Optional[bool] = None
    adjustments: Dict[str, float] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    def itemized_note(self) -> str:
        """Compact audit trail: EV, each deduction/addition, and the equity value."""
        parts = [f"EV={self.enterprise_value:,.0f}"]
        for key, label in (
            ("net_debt", "净债务"),
            ("minority_interest", "少数股东权益"),
            ("preferred_equity", "优先股"),
            ("lease_liabilities", "租赁负债"),
            ("other_claims", "其他索偿"),
        ):
            v = self.adjustments.get(key, 0.0)
            if v:
                parts.append(f"{label}={v:,.0f}")
        noa = self.adjustments.get("non_operating_assets", 0.0)
        if noa:
            parts.append(f"+非经营性资产={noa:,.0f}")
        parts.append(f"→ 股权价值={self.equity_value:,.0f}")
        return "  ".join(parts)


def _resolve_claims(
    market: MarketData,
    *,
    other_claims: float,
    lease_liabilities: Optional[float],
    net_debt_includes_minority: bool,
    net_debt_includes_preferred: bool,
) -> Tuple[float, float, float, float, float, float, List[str]]:
    """Resolve the claim components once, with double-count guards.

    Returns ``(net_debt, dd_minority, dd_preferred, dd_leases, other, non_op,
    notes)`` where ``dd_*`` are the amounts that should actually be deducted in
    the EV → Equity direction (zero when already inside ``net_debt``).
    """
    net_debt = market.net_debt_or_zero()
    notes: List[str] = []
    if market.net_debt is None and market.total_debt is None:
        notes.append("净债务缺失（无 Total Debt / Cash）→ 按 0 处理，桥接精度受限")

    minority = float(market.minority_interest or 0.0)
    preferred = float(market.preferred_equity or 0.0)
    non_op = float(market.non_operating_assets or 0.0)
    other = float(other_claims or 0.0)

    dd_minority = 0.0
    if minority:
        if net_debt_includes_minority:
            notes.append("少数股东权益已包含在净债务中 → 不再重复扣除")
        else:
            dd_minority = minority

    dd_preferred = 0.0
    if preferred:
        if net_debt_includes_preferred:
            notes.append("优先股已包含在净债务中 → 不再重复扣除")
        else:
            dd_preferred = preferred

    dd_leases = 0.0
    if lease_liabilities:
        if market.leases_in_debt is True:
            notes.append("租赁负债已包含在 Total Debt 中 → 不再重复扣除")
        else:
            dd_leases = float(lease_liabilities)
            if market.leases_in_debt is None:
                notes.append(
                    "租赁负债口径未知 → 按独立负债扣除（请核对 Total Debt 是否已含租赁）"
                )

    return net_debt, dd_minority, dd_preferred, dd_leases, other, non_op, notes


def enterprise_to_equity(
    enterprise_value: Optional[float],
    market: MarketData,
    *,
    other_claims: float = 0.0,
    lease_liabilities: Optional[float] = None,
    net_debt_includes_minority: bool = False,
    net_debt_includes_preferred: bool = False,
) -> EquityBridge:
    """Bridge an enterprise value to equity value for a (possibly complex) capital
    structure. See the module docstring for the formula and the no-double-count
    rules.

    Parameters
    ----------
    enterprise_value:
        The operating enterprise value produced by the calling model.
    market:
        Market data carrying the claim components (net debt / minority interest /
        preferred equity / non-operating assets / lease convention).
    lease_liabilities:
        Lease liabilities to deduct **only** when they are not already inside
        ``total_debt`` (guarded by ``market.leases_in_debt``).
    """
    ev = float(enterprise_value or 0.0)
    net_debt, dd_minority, dd_preferred, dd_leases, other, non_op, notes = (
        _resolve_claims(
            market,
            other_claims=other_claims,
            lease_liabilities=lease_liabilities,
            net_debt_includes_minority=net_debt_includes_minority,
            net_debt_includes_preferred=net_debt_includes_preferred,
        )
    )

    equity_value = (
        ev - net_debt - dd_minority - dd_preferred - dd_leases - other + non_op
    )

    adjustments: Dict[str, float] = {
        "net_debt": -net_debt,
        "minority_interest": -dd_minority,
        "preferred_equity": -dd_preferred,
        "lease_liabilities": -dd_leases,
        "other_claims": -other,
        "non_operating_assets": non_op,
    }

    return EquityBridge(
        enterprise_value=ev,
        net_debt=net_debt,
        minority_interest=dd_minority,
        preferred_equity=dd_preferred,
        lease_liabilities=dd_leases,
        other_claims=other,
        non_operating_assets=non_op,
        equity_value=equity_value,
        leases_in_debt=market.leases_in_debt,
        adjustments=adjustments,
        notes=notes,
    )


def equity_to_enterprise(
    equity_value: Optional[float],
    market: MarketData,
    *,
    other_claims: float = 0.0,
    lease_liabilities: Optional[float] = None,
    net_debt_includes_minority: bool = False,
    net_debt_includes_preferred: bool = False,
) -> float:
    """Exact inverse of :func:`enterprise_to_equity` — the equity → EV bridge.

    Used by equity-anchored multiples (P/E, P/B, FCF Yield) that must lift an
    equity value back to an enterprise value on the *same* claim basis.
    """
    eq = float(equity_value or 0.0)
    net_debt, dd_minority, dd_preferred, dd_leases, other, non_op, _ = _resolve_claims(
        market,
        other_claims=other_claims,
        lease_liabilities=lease_liabilities,
        net_debt_includes_minority=net_debt_includes_minority,
        net_debt_includes_preferred=net_debt_includes_preferred,
    )
    return eq + net_debt + dd_minority + dd_preferred + dd_leases + other - non_op


def equity_bridge_components(market: MarketData) -> Dict[str, Any]:
    """Report whether any complex-structure component is present (for the report).

    A simple ``ev - net_debt`` and a full bridge give the same answer when every
    component is ``None``; the report uses this to decide whether to show the
    itemised bridge or a single-line bridge.
    """
    return {
        "minority_interest": market.minority_interest,
        "preferred_equity": market.preferred_equity,
        "non_operating_assets": market.non_operating_assets,
        "leases_in_debt": market.leases_in_debt,
        "has_complex_structure": any(
            v is not None
            for v in (
                market.minority_interest,
                market.preferred_equity,
                market.non_operating_assets,
                market.leases_in_debt,
            )
        ),
    }


__all__ = [
    "EquityBridge",
    "enterprise_to_equity",
    "equity_to_enterprise",
    "equity_bridge_components",
]
