"""
analysis/expectation.py - Market-Implied Expectations & Gap Analysis
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from config import ScenarioType, get_logger, resolve_forecast_horizon
from data.models import FinancialData
from models.reverse_dcf import ReverseDCFModel

log = get_logger("analysis.expectation")


@dataclass
class ImpliedExpectations:
    implied_fcf_cagr: Optional[float] = None
    implied_revenue_cagr: Optional[float] = None
    implied_revenue_cagr_source: Optional[str] = None
    # Structured bound (Session #31): when the market price sits outside what the
    # business type's sanctioned growth band can justify, ``implied_revenue_cagr``
    # stays None but this carries ``{"kind": "above_band_ceiling"|"below_band_floor",
    # "value": <band edge>, "ev_at_bound": <EV>}`` — an honest bound, not a point
    # estimate. ``implied_base_cagr_is_bound`` marks that the one-at-a-time implied
    # drivers below were solved with growth pinned at that bound edge.
    implied_revenue_cagr_bound: Optional[Dict[str, Any]] = None
    implied_base_cagr_is_bound: Optional[bool] = None
    current_price: Optional[float] = None
    reverse_dcf_status: Optional[str] = None
    # ---- Phase 2 (Session #17): one-at-a-time implied drivers --------------
    # Each is the market-implied value of that single assumption *with every
    # other input held at its base case*. ``*_status`` is the ``SolverStatus``
    # value; ``None`` value + a status of NO_SOLUTION_IN_RANGE means the target
    # price is unreachable inside the constraint bounds.
    implied_operating_margin: Optional[float] = None
    implied_operating_margin_status: Optional[str] = None
    implied_fcf_margin: Optional[float] = None
    implied_fcf_margin_status: Optional[str] = None
    implied_wacc: Optional[float] = None
    implied_wacc_status: Optional[str] = None
    implied_terminal_growth: Optional[float] = None
    implied_terminal_growth_status: Optional[str] = None
    # Terminal-value suppression (Session #18): True when the terminal FCF ≤ 0 and
    # the terminal value was suppressed, so every implied value is only supported
    # by explicit-period cash flows (needs a turnaround assumption).
    terminal_fcf_negative: Optional[bool] = None
    implied_constraint_notes: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass
class ExpectationGap:
    historical_revenue_cagr: Optional[float] = None
    historical_fcf_cagr: Optional[float] = None
    base_forecast_revenue_cagr: Optional[float] = None
    base_forecast_fcf_cagr: Optional[float] = None
    implied_revenue_cagr: Optional[float] = None
    implied_revenue_cagr_source: Optional[str] = None
    # Structured-bound pass-through (Session #32): when the price sits outside the
    # sanctioned growth band, ``implied_revenue_cagr`` is None but the honest
    # "≥ ceiling / ≤ floor" bound lives on ``ImpliedExpectations``. Mirror it here
    # so the gap section cannot print "N/A" for a quantity the implied section
    # already states (the two sections must agree).
    implied_revenue_cagr_bound: Optional[Dict[str, Any]] = None
    implied_revenue_cagr_is_bound: Optional[bool] = None
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
        ie = result.breakdown.get("implied_expectations") or {}

        def _val(key: str) -> Optional[float]:
            s = ie.get(key)
            return getattr(s, "value", None) if s is not None else None

        def _status(key: str) -> Optional[str]:
            s = ie.get(key)
            return getattr(s, "status", None) if s is not None else None

        constraint_notes: List[str] = []
        for key in (
            "implied_operating_margin",
            "implied_fcf_margin",
            "implied_wacc",
            "implied_terminal_growth",
        ):
            s = ie.get(key)
            note = getattr(s, "note", None) if s is not None else None
            if note:
                constraint_notes.append(note)

        # Terminal-value suppression (Session #18): prefer the reverse-DCF solve
        # flag, else fall back to the implied-expectations block's base projection.
        tv_suppressed = result.breakdown.get("terminal_fcf_negative")
        if tv_suppressed is None:
            tv_suppressed = ie.get("terminal_fcf_negative")
        if tv_suppressed:
            constraint_notes.append(
                "⚠️ 终期 FCF ≤ 0，终值已抑制（Terminal Value Suppressed — Turnaround "
                "Assumption Required）：隐含值仅由显式期现金流支撑，非正常永续经营价值"
            )

        return ImpliedExpectations(
            implied_fcf_cagr=result.breakdown.get("implied_fcf_cagr"),
            implied_revenue_cagr=result.breakdown.get("implied_revenue_cagr"),
            implied_revenue_cagr_source=result.breakdown.get("implied_revenue_cagr_source"),
            implied_revenue_cagr_bound=result.breakdown.get("implied_revenue_cagr_bound"),
            implied_base_cagr_is_bound=result.breakdown.get("implied_base_cagr_is_bound"),
            current_price=data.market.current_price,
            reverse_dcf_status=result.status.value,
            implied_operating_margin=_val("implied_operating_margin"),
            implied_operating_margin_status=_status("implied_operating_margin"),
            implied_fcf_margin=_val("implied_fcf_margin"),
            implied_fcf_margin_status=_status("implied_fcf_margin"),
            implied_wacc=_val("implied_wacc"),
            implied_wacc_status=_status("implied_wacc"),
            implied_terminal_growth=_val("implied_terminal_growth"),
            implied_terminal_growth_status=_status("implied_terminal_growth"),
            terminal_fcf_negative=bool(tv_suppressed) if tv_suppressed is not None else None,
            implied_constraint_notes=constraint_notes,
            notes=result.notes,
        )

    def historical_cagr(self, data: FinancialData, attr: str = "revenue") -> Optional[float]:
        """CAGR across the full annual window, or None when it is undefined.

        Filtering out non-positive values before the ratio is computed silently
        shortens the span and can invert the sign of the answer: VST's FCF runs
        -816M (2022) -> 1318M (2025), an improvement, yet a ``> 0`` filter drops
        the loss year, relabels the window as 2 years and reports -40.9%. A CAGR
        that crosses a sign change is undefined, so return None and let the
        caller state "not computable" rather than print a fabricated rate.
        """
        series = [
            getattr(s, attr)
            for s in data.annual_income
            if getattr(s, attr, None) is not None
        ]
        if len(series) < 2:
            return None
        oldest, latest = series[-1], series[0]
        if oldest <= 0 or latest <= 0:
            return None
        n = len(series) - 1
        return (latest / oldest) ** (1 / n) - 1

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

        # Same horizon as DCF / Reverse DCF for this business type (Session #16).
        horizon = resolve_forecast_horizon(business_type_from_profile(profile))
        eng = ForecastEngine(
            horizon_years=horizon,
            business_type=business_type_from_profile(profile),
        )
        if attr == "free_cash_flow":
            # Projected FCF is bridge-caliber (NOPAT+D&A−capex−ΔNWC). Reported
            # TTM FCF is OCF−capex and adds SBC back, so mixing the two calibers
            # made a rising forecast read as negative growth.
            start = eng.bridge_fcf_anchor(data) or start
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
            implied_revenue_cagr_source=implied.implied_revenue_cagr_source,
            implied_revenue_cagr_bound=implied.implied_revenue_cagr_bound,
            implied_revenue_cagr_is_bound=implied.implied_base_cagr_is_bound,
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
