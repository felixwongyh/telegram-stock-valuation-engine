"""
analysis/model_agreement.py - Model Agreement & Valuation Spread
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median, pstdev
from typing import Dict, List, Optional

from config import get_logger
from models.base import ValuationResult

log = get_logger("analysis.model_agreement")


@dataclass
class ModelAgreement:
    n_applicable: int
    n_solved: int
    values: Dict[str, Optional[float]]
    median_value: Optional[float] = None
    mean_value: Optional[float] = None
    low_value: Optional[float] = None
    high_value: Optional[float] = None
    std_dev: Optional[float] = None
    cv: Optional[float] = None
    spread_pct: Optional[float] = None
    agreement_level: str = "Unknown"
    notes: List[str] = field(default_factory=list)


class ModelAgreementAnalyzer:
    """Summarizes the agreement across multiple valuation models."""

    def analyze(self, results: Dict[str, ValuationResult], current_price: Optional[float] = None) -> ModelAgreement:
        n_applicable = len(results)
        solved: Dict[str, float] = {}
        values_all: Dict[str, Optional[float]] = {}
        for name, r in results.items():
            if r.is_success() and r.value_per_share is not None:
                solved[name] = r.value_per_share
                values_all[name] = r.value_per_share
            else:
                values_all[name] = None

        vals = list(solved.values())
        n_solved = len(vals)

        ma = ModelAgreement(
            n_applicable=n_applicable,
            n_solved=n_solved,
            values=values_all,
        )

        if vals:
            mv = sorted(vals)
            ma.low_value = mv[0]
            ma.high_value = mv[-1]
            ma.mean_value = sum(vals) / len(vals)
            ma.median_value = median(vals)
            if len(vals) >= 2:
                ma.std_dev = pstdev(vals)
                if ma.mean_value and ma.mean_value > 0:
                    ma.cv = ma.std_dev / ma.mean_value
            if ma.low_value is not None and ma.high_value is not None and ma.median_value and ma.median_value > 0:
                ma.spread_pct = (ma.high_value - ma.low_value) / ma.median_value

            if ma.cv is not None:
                if ma.cv < 0.10:
                    ma.agreement_level = "Very Strong"
                elif ma.cv < 0.20:
                    ma.agreement_level = "Strong"
                elif ma.cv < 0.35:
                    ma.agreement_level = "Moderate"
                elif ma.cv < 0.55:
                    ma.agreement_level = "Weak"
                else:
                    ma.agreement_level = "Very Weak"
            else:
                ma.agreement_level = "N/A (single model)"
        else:
            ma.notes.append("No models produced a valid value")

        if n_solved < n_applicable:
            ma.notes.append(f"{n_applicable - n_solved} of {n_applicable} applicable models failed")

        if current_price and ma.median_value is not None and ma.median_value > 0:
            pct = (current_price - ma.median_value) / ma.median_value
            ma.notes.append(f"当前价格 ${current_price:.2f} vs 中位估值 ${ma.median_value:.2f} ({pct:+.1%})")

        return ma


__all__ = ["ModelAgreementAnalyzer", "ModelAgreement"]
