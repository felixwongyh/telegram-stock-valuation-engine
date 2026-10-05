"""
analysis/expectation.py - Market-Implied Expectations & Gap Analysis
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from config import DEFAULT_FORECAST_HORIZON_YEARS, ScenarioType, get_logger
from data.models import FinancialData
from models.base import ValuationResult
from models.reverse_dcf import ReverseDCFModel

log = get_logger("analysis.expectation")


@dataclass
class ImpliedExpectations:
    implied_fcf_cagr: Optional[float] = None
    implied_revenue_cagr: Optional[float] = None
    current_price: Optional[float] = None
    reverse_dcf_status: Optional[str] = None
    notes: List[str] = field(default_factory=list)


@dataclass
class ExpectationGap:
    historical_revenue_cagr: Optional[float] = None
    historical_fcf_cagr: Optional[float] = None
    base_forecast_revenue_cagr: Optional[float] = None
    base_forecast_fcf_cagr: Optional[float] = None
    implied_revenue_cagr: Optional[float] = None
    implied_fcf_cagr: Optional[float] = None
    revenue_gap_vs_history: Optional[float] = None
    fcf_gap_vs_history: Optional[float] = None
    notes: List[str] = field(default_factory=list)


class ExpectationAnalyzer:
    """Compares historical actuals, base forecast, and market-implied expectations."""

    def implied_expectations(
        self, data: FinancialData, profile: Any
    ) -> ImpliedExpectations:
        r = ReverseDCFModel()
        ok, reasons = r.applicability_check(data, profile)
        if not ok:
            return ImpliedExpectations(
                current_price=data.market.current_price,
                reverse_dcf_status="Not Applicable",
                notes=reasons,
            )
        result = r.calculate(data, profile)
        return ImpliedExpectations(
            implied_fcf_cagr=result.breakdown.get("implied_fcf_cagr"),
            implied_revenue_cagr=result.breakdown.get("implied_revenue_cagr"),
            current_price=data.market.current_price,
            reverse_dcf_status=result.status.value,
            notes=result.notes,
        )

    def historical_cagr(self, data: FinancialData, attr: str = "revenue") -> Optional[float]:
        series = [getattr(s, attr) for s in data.annual_income if getattr(s, attr) is not None and getattr(s, attr) > 0]
        if len(series) < 2:
            return None
        n = len(series) - 1
        return (series[0] / series[-1]) ** (1 / n) - 1

    def forecast_cagr(
        self,
        data: FinancialData,
        attr: str = "revenue",
        profile: Any = None,
    ) -> Optional[float]:
        ttm = data.ttm
        if ttm is None:
            return None
        start = getattr(ttm, attr)
        if start is None or start <= 0:
            return None
        from forecasts.forecast import ForecastEngine
        from forecasts.nwc_utils import business_type_from_profile

        eng = ForecastEngine(
            horizon_years=DEFAULT_FORECAST_HORIZON_YEARS,
            business_type=business_type_from_profile(profile),
        )
        fc = eng.build_all(data).get(ScenarioType.BASE, [])
        if not fc:
            return None
        end = getattr(fc[-1], attr)
        if end is None or end <= 0:
            return None
        n = len(fc)
        return (end / start) ** (1 / n) - 1

    def gap_analysis(
        self, data: FinancialData, profile: Any
    ) -> Tuple[ImpliedExpectations, ExpectationGap]:
        implied = self.implied_expectations(data, profile)
        hist_rev = self.historical_cagr(data, "revenue")
        hist_fcf = self.historical_cagr(data, "free_cash_flow")
        base_rev = self.forecast_cagr(data, "revenue", profile)
        base_fcf = self.forecast_cagr(data, "free_cash_flow", profile)

        gap = ExpectationGap(
            historical_revenue_cagr=hist_rev,
            historical_fcf_cagr=hist_fcf,
            base_forecast_revenue_cagr=base_rev,
            base_forecast_fcf_cagr=base_fcf,
            implied_revenue_cagr=implied.implied_revenue_cagr,
            implied_fcf_cagr=implied.implied_fcf_cagr,
        )
        if implied.implied_revenue_cagr is not None and hist_rev is not None:
            gap.revenue_gap_vs_history = implied.implied_revenue_cagr - hist_rev
        if implied.implied_fcf_cagr is not None and hist_fcf is not None:
            gap.fcf_gap_vs_history = implied.implied_fcf_cagr - hist_fcf

        notes: List[str] = []
        if implied.implied_fcf_cagr is not None:
            if implied.implied_fcf_cagr > 0.25:
                notes.append("Market pricing in very high FCF CAGR (>25%); may be hard to achieve")
            elif implied.implied_fcf_cagr < 0:
                notes.append("Market pricing in declining FCF; distressed scenario implied")
        gap.notes = notes
        return implied, gap


__all__ = ["ExpectationAnalyzer", "ImpliedExpectations", "ExpectationGap"]
