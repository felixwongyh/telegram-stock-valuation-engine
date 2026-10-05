"""
models/base.py - Base Valuation Model Interface
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from config import ModelName, SolverStatus, get_logger

log = get_logger("models.base")


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


__all__ = ["ValuationModel", "ValuationResult", "ValuationAssumption"]
