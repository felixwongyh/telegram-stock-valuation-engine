"""
models/base.py - Base Valuation Model Interface
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from config import ModelName, SolverStatus, get_logger

log = get_logger("models.base")


class ShareCountBasis(str, Enum):
    """Which share-count caliber a model divided its equity value by (P0-3).

    Two per-share numbers are only directly comparable when they share a basis.
    A BASIC count and a DILUTED count of the same company can differ by several
    percent (options/RSUs); a MARKET count is derived from ``market_cap ÷ price``
    while a TTM count comes from the latest financial statements. Mixing them in
    one "consensus median" silently compares different units — which is the
    defect this contract exists to prevent.
    """
    BASIC = "basic"
    DILUTED = "diluted"
    TTM = "ttm"
    MARKET = "market"
    UNKNOWN = "unknown"


@dataclass
class ShareCount:
    """Per-model share-count provenance (the contract demanded by P0-3).

    Every model that produces a ``value_per_share`` must attach one of these so
    the aggregation layer can (a) show which denominator was used, and (b) refuse
    to mix incompatible denominators in one consensus median.
    """
    shares_used: Optional[float] = None
    source: str = ""
    as_of: Optional[str] = None
    basis: str = ShareCountBasis.UNKNOWN.value
    reliable: bool = True

    def as_dict(self) -> Dict[str, Any]:
        return {
            "shares_used": self.shares_used,
            "shares_source": self.source,
            "shares_as_of": self.as_of,
            "shares_basis": self.basis,
            "shares_reliable": self.reliable,
        }


def make_share_count(
    shares: Optional[float],
    source: str,
    basis: "ShareCountBasis | str",
    as_of: Optional[str] = None,
    reliable: bool = True,
) -> ShareCount:
    """Build a :class:`ShareCount`, normalising the basis label."""
    b = basis.value if isinstance(basis, ShareCountBasis) else str(basis)
    return ShareCount(
        shares_used=float(shares) if shares is not None else None,
        source=source,
        as_of=as_of,
        basis=b,
        reliable=reliable,
    )


def make_comparability(
    *,
    currency: Optional[str] = None,
    financial_period: Optional[str] = None,
    valuation_date: Optional[str] = None,
    value_basis: str = "equity_per_share",
    peer_valid: Optional[bool] = None,
) -> Dict[str, Any]:
    """Declare the data caliber a model's per-share value was computed from (P1-8).

    Two models can each "solve" yet still be incomparable: one divides a
    forecast-based value by a TTM share count, another divides a TTM earnings
    multiple by a market share count. The aggregation layer therefore needs each
    model to declare WHICH caliber it used — currency, financial period,
    valuation date, value basis, peer validity — so a comparability gate can
    refuse to mix incompatible calibers in one consensus median.
    """
    out: Dict[str, Any] = {"value_basis": value_basis}
    if currency:
        out["currency"] = currency
    if financial_period:
        out["financial_period"] = str(financial_period)
    if valuation_date:
        # Normalise to an ISO date (YYYY-MM-DD) so the gate can compare dates
        # regardless of whether a str / datetime / date was supplied.
        if isinstance(valuation_date, str):
            out["valuation_date"] = valuation_date[:10]
        else:
            iso = getattr(valuation_date, "isoformat", None)
            out["valuation_date"] = (str(iso())[:10] if callable(iso) else str(valuation_date)[:10])
    if peer_valid is not None:
        out["peer_valid"] = bool(peer_valid)
    return out


@dataclass
class ValuationAssumption:
    key: str
    value: Any
    unit: Optional[str] = None
    source: str = "Default"


@dataclass
class ValuationResult:
    model_name: str
    status: SolverStatus
    value_per_share: Optional[float] = None
    enterprise_value: Optional[float] = None
    equity_value: Optional[float] = None
    assumptions: List[ValuationAssumption] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    breakdown: Dict[str, Any] = field(default_factory=dict)
    data_quality_score: int = 100
    # Share-count provenance (P0-3). None => model did not declare a denominator
    # (legacy / not per-share); the aggregation layer will not validate it.
    share_count: Optional[ShareCount] = None
    # Data-caliber declaration (P1-8) consumed by the Valuation Comparability
    # Gate: currency / financial_period / valuation_date / value_basis /
    # peer_valid. Empty ⇒ nothing declared (the gate then has no basis to
    # exclude this model on — absence of evidence is not a conflict).
    comparability: Dict[str, Any] = field(default_factory=dict)

    def is_success(self) -> bool:
        return self.status in (SolverStatus.SOLVED, SolverStatus.APPROXIMATE)

    def summary(self) -> str:
        if not self.is_success():
            return f"{self.model_name}: {self.status.value} - {'; '.join(self.notes) if self.notes else 'N/A'}"
        pps = f"${self.value_per_share:,.2f}" if self.value_per_share is not None else "N/A"
        return f"{self.model_name}: {pps}/share ({self.status.value})"


class ValuationModel(ABC):
    """Abstract base class for all valuation models."""

    NAME: ModelName = ModelName.DCF

    def __init__(self, name: Optional[str] = None) -> None:
        self.model_name = (name or self.NAME.value) if self.NAME else "Unknown"

    @abstractmethod
    def applicability_check(self, data: Any, profile: Any) -> tuple[bool, List[str]]:
        """Return (is_applicable, reasons_if_not)."""
        ...

    @abstractmethod
    def calculate(self, data: Any, profile: Any, **kwargs) -> ValuationResult:
        """Compute valuation and return structured result."""
        ...

    def run(self, data: Any, profile: Any, **kwargs) -> ValuationResult:
        """Full pipeline: check applicability, run, validate."""
        ok, reasons = self.applicability_check(data, profile)
        if not ok:
            return ValuationResult(
                model_name=self.model_name,
                status=SolverStatus.INSUFFICIENT_DATA,
                notes=reasons,
            )
        result = self.calculate(data, profile, **kwargs)
        result = self._validate(result)
        return result

    def _validate(self, result: ValuationResult) -> ValuationResult:
        if result.value_per_share is not None:
            if result.value_per_share < 0:
                result.notes.append("Warning: negative value/share; model likely misapplied")
            elif result.value_per_share == 0:
                result.notes.append("Warning: zero value/share")
            elif result.value_per_share > 1e6:
                result.notes.append("Warning: extremely high value/share; sanity check inputs")
        return result


__all__ = [
    "ValuationModel", "ValuationResult", "ValuationAssumption",
    "ShareCount", "ShareCountBasis", "make_share_count", "make_comparability",
]
