"""
forecasts/forecast.py - Forecast Engine
Builds Bear/Base/Bull forecasts from historical data.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from config import (
    DEFAULT_DCF_CONFIG,
    DEFAULT_FORECAST_HISTORY,
    DEFAULT_FORECAST_HORIZON_YEARS,
    DEFAULT_SCENARIO_CONFIG,
    ScenarioConfig,
    ScenarioType,
    get_logger,
)
from data.models import FinancialData, ForecastPeriod
from forecasts.nwc_utils import (
    adjust_marginal_nwc_for_business_type,
    forecast_nwc_change,
    marginal_nwc_ratio,
    resolve_change_in_nwc,
)

log = get_logger("forecasts.forecast")


class ForecastEngine:
    """Generate Bear/Base/Bull scenario forecasts."""

    def __init__(
        self,
        horizon_years: int = DEFAULT_FORECAST_HORIZON_YEARS,
        scenario_config: ScenarioConfig = DEFAULT_SCENARIO_CONFIG,
        business_type: Optional[str] = None,
    ) -> None:
        self.horizon_years = horizon_years
        self.sc = scenario_config
        self.business_type = business_type

    def build_all(
        self, data: FinancialData
    ) -> Dict[ScenarioType, List[ForecastPeriod]]:
        return {
            ScenarioType.BEAR: self._build_scenario(data, ScenarioType.BEAR),
            ScenarioType.BASE: self._build_scenario(data, ScenarioType.BASE),
            ScenarioType.BULL: self._build_scenario(data, ScenarioType.BULL),
        }

    def _build_scenario(
        self, data: FinancialData, scenario: ScenarioType
    ) -> List[ForecastPeriod]:
        base = self._build_base(data)
        if base is None:
            return []
        if scenario == ScenarioType.BASE:
            return base
        rev_mult, margin_mult = self._get_scenario_multipliers(scenario)
        return self._apply_multipliers(base, rev_mult, margin_mult)

    def _get_scenario_multipliers(
        self, scenario: ScenarioType
    ) -> Tuple[float, float]:
        if scenario == ScenarioType.BEAR:
            return self.sc.bear_revenue_mult, self.sc.bear_margin_mult
        elif scenario == ScenarioType.BULL:
            return self.sc.bull_revenue_mult, self.sc.bull_margin_mult
        return self.sc.base_revenue_mult, self.sc.base_margin_mult

    def _build_base(self, data: FinancialData) -> Optional[List[ForecastPeriod]]:
        ttm = data.ttm
        if ttm is None or ttm.revenue is None or ttm.revenue <= 0:
            return None

        hist_rev_cagr, hist_gm, hist_om, hist_da_ratio, hist_capex_ratio, hist_nwc_ratio, hist_tax_rate = (
            self._extract_history(data)
        )

        periods: List[ForecastPeriod] = []
        current_rev = ttm.revenue
        shares = ttm.shares_outstanding

        for i in range(self.horizon_years):
            decay = 1.0 - (i / max(1, self.horizon_years)) * 0.5
            growth = hist_rev_cagr * decay
            if i == 0:
                growth = max(-0.30, min(0.60, growth))
            else:
                growth = max(-0.20, min(0.40, growth))

            next_rev = current_rev * (1 + growth)
            delta_rev = next_rev - current_rev
            gm = hist_gm
            om = max(-0.30, min(0.60, hist_om * (1 - 0.05 * i)))
            gross = next_rev * gm
            op_inc = next_rev * om
            tax = max(0.0, min(0.50, hist_tax_rate))
            nopat = op_inc * (1 - tax)
            da = next_rev * hist_da_ratio
            capex = next_rev * hist_capex_ratio
            nwc = forecast_nwc_change(delta_rev, hist_nwc_ratio)
            fcf = nopat + da - capex - nwc

            fp = ForecastPeriod(
                year_index=i + 1,
                label=f"Year {i + 1}",
                revenue=next_rev,
                revenue_growth=growth,
                gross_profit=gross,
                gross_margin=gm,
                operating_income=op_inc,
                operating_margin=om,
                nopat=nopat,
                depreciation=da,
                capex=capex,
                change_in_nwc=nwc,
                free_cash_flow=fcf,
                effective_tax_rate=tax,
                shares_outstanding=shares,
            )
            periods.append(fp)
            current_rev = next_rev

        return periods

    def _extract_history(self, data: FinancialData) -> Tuple[float, float, float, float, float, float, float]:
        annuals = data.annual_income[:5]
        for s in annuals:
            if s.change_in_nwc is None:
                inferred = resolve_change_in_nwc(s)
                if inferred is not None:
                    s.change_in_nwc = inferred

        fb = DEFAULT_FORECAST_HISTORY
        if len(annuals) < 2:
            return (
                fb.rev_cagr,
                fb.gross_margin,
                fb.operating_margin,
                fb.da_to_revenue,
                fb.capex_to_revenue,
                fb.marginal_nwc_ratio,
                DEFAULT_DCF_CONFIG.tax_rate,
            )

        revs = [s.revenue for s in annuals if s.revenue is not None and s.revenue > 0]
        if len(revs) < 2:
            rev_cagr = fb.rev_cagr
        else:
            n = len(revs) - 1
            rev_cagr = (revs[0] / revs[-1]) ** (1 / n) - 1
            rev_cagr = max(-0.15, min(0.40, rev_cagr))

        def _safe_avg(attr: str, divisor_attr: str) -> float:
            ratios = []
            for s in annuals:
                num = getattr(s, attr)
                den = getattr(s, divisor_attr)
                if num is not None and den is not None and den > 0:
                    ratios.append(num / den)
            return sum(ratios) / len(ratios) if ratios else 0.0

        gm = _safe_avg("gross_profit", "revenue")
        if gm <= 0 or gm > 0.95:
            gm = fb.gross_margin
        om = _safe_avg("operating_income", "revenue")
        om = max(-0.10, min(0.50, om if om else fb.operating_margin))
        da_ratio = _safe_avg("depreciation_amortization", "revenue")
        if da_ratio <= 0:
            da_ratio = fb.da_to_revenue
        capex_ratio = _safe_avg("capex", "revenue")
        capex_ratio = abs(capex_ratio) if capex_ratio else fb.capex_to_revenue

        nwc_ratio, _nwc_method = marginal_nwc_ratio(annuals)
        nwc_ratio = adjust_marginal_nwc_for_business_type(nwc_ratio, self.business_type)

        tax_ratios = []
        for s in annuals:
            if s.income_tax is not None and s.operating_income is not None and s.operating_income > 0:
                tr = s.income_tax / s.operating_income
                if 0.0 <= tr <= 0.50:
                    tax_ratios.append(tr)
        tax_rate = sum(tax_ratios) / len(tax_ratios) if tax_ratios else DEFAULT_DCF_CONFIG.tax_rate

        return rev_cagr, gm, om, da_ratio, capex_ratio, nwc_ratio, tax_rate

    def _apply_multipliers(
        self, base: List[ForecastPeriod], rev_mult: float, margin_mult: float
    ) -> List[ForecastPeriod]:
        out: List[ForecastPeriod] = []
        for p in base:
            np_rev = p.revenue * rev_mult if p.revenue else None
            np_op_inc = p.operating_income * margin_mult if p.operating_income else None
            np_gm = p.gross_margin
            np_om = (np_op_inc / np_rev) if (np_rev and np_rev > 0 and np_op_inc is not None) else p.operating_margin
            np_gp = np_rev * np_gm if np_rev and np_gm is not None else None
            np_nopat = (np_op_inc * (1 - p.effective_tax_rate)) if (np_op_inc is not None and p.effective_tax_rate is not None) else None
            np_da = np_rev * (p.depreciation / p.revenue) if (np_rev and p.revenue and p.depreciation is not None and p.revenue > 0) else p.depreciation
            np_capex = np_rev * (p.capex / p.revenue) if (np_rev and p.revenue and p.capex is not None and p.revenue > 0) else p.capex
            np_nwc = (
                np_rev * (p.change_in_nwc / p.revenue)
                if (np_rev and p.revenue and p.change_in_nwc is not None and p.revenue > 0)
                else p.change_in_nwc
            )
            if np_nopat is not None and np_da is not None and np_capex is not None and np_nwc is not None:
                np_fcf = np_nopat + np_da - np_capex - np_nwc
            else:
                np_fcf = None
            out.append(ForecastPeriod(
                year_index=p.year_index,
                label=p.label,
                revenue=np_rev,
                revenue_growth=p.revenue_growth,
                gross_profit=np_gp,
                gross_margin=np_gm,
                operating_income=np_op_inc,
                operating_margin=np_om,
                nopat=np_nopat,
                depreciation=np_da,
                capex=np_capex,
                change_in_nwc=np_nwc,
                free_cash_flow=np_fcf,
                effective_tax_rate=p.effective_tax_rate,
                shares_outstanding=p.shares_outstanding,
            ))
        return out


__all__ = ["ForecastEngine"]
