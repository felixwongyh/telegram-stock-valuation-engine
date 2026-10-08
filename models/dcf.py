"""
models/dcf.py - Discounted Cash Flow Model
WACC + Terminal Growth are now auditable bottom-up calculations.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from config import (
    DCFConfig,
    DEFAULT_DCF_CONFIG,
    DEFAULT_FORECAST_HORIZON_YEARS,
    LONG_TERM_NOMINAL_GDP,
    ModelName,
    ScenarioType,
    SolverStatus,
    get_logger,
)
from data.models import FinancialData
from forecasts.forecast import ForecastEngine
from models.base import ValuationAssumption, ValuationModel, ValuationResult
from valuation.terminal_growth import (
    TerminalGrowthCalculator,
    TerminalGrowthRange,
)
from valuation.wacc import WaccBreakdown, WaccCalculator

log = get_logger("models.dcf")


class DCFModel(ValuationModel):
    NAME = ModelName.DCF

    def __init__(
        self,
        config: DCFConfig = DEFAULT_DCF_CONFIG,
        forecast_horizon: int = DEFAULT_FORECAST_HORIZON_YEARS,
    ) -> None:
        super().__init__()
        self.cfg = config
        self.horizon = forecast_horizon
        self._wacc_calc = WaccCalculator(config=config)
        self._tvg_calc = TerminalGrowthCalculator(
            long_term_nominal_gdp=LONG_TERM_NOMINAL_GDP,
        )

    def applicability_check(
        self, data: FinancialData, profile: Any
    ) -> Tuple[bool, List[str]]:
        reasons: List[str] = []
        if profile and getattr(profile, "is_financial_institution", False):
            reasons.append("DCF unreliable for financial institutions (use DDM/RIM)")
        if profile and getattr(profile, "is_reit", False):
            reasons.append("REITs prefer NAV/FFO over FCF-DCF")
        ttm = data.ttm
        if ttm is None:
            reasons.append("No TTM statement")
        else:
            if ttm.revenue is None:
                reasons.append("TTM revenue missing")
            if ttm.operating_income is None:
                reasons.append("TTM operating_income missing")
            if ttm.shares_outstanding is None or ttm.shares_outstanding <= 0:
                reasons.append("Shares outstanding invalid")
        if data.market.current_price is None:
            reasons.append("Current price missing (needed for WACC sanity)")
        return (len(reasons) == 0, reasons)

    def calculate(
        self, data: FinancialData, profile: Any, **kwargs
    ) -> ValuationResult:
        # ---- 1. Dynamic WACC ----
        wacc_bd: WaccBreakdown = self._wacc_calc.calculate(data, profile)
        wacc = wacc_bd.wacc

        # ---- 2. Terminal Growth (Low / Base / High) ----
        tvg: TerminalGrowthRange = self._tvg_calc.calculate(data, wacc=wacc)
        tg = tvg.base
        tg_low = tvg.low
        tg_high = tvg.high

        assumptions = [
            ValuationAssumption("WACC", round(wacc, 4), "%", wacc_bd.sources.get("WACC (final)", "CAPM + D/E")),
            # Legacy key (保留以兼容 tests)
            ValuationAssumption("Terminal Growth", round(tg, 4), "%", "See Terminal Growth (Base/Low/High)"),
            ValuationAssumption(
                "Terminal Growth (Base)", round(tg, 4), "%",
                f"min(norm={tvg.normalized_growth:.3%}, LT_GDP={tvg.long_term_nominal_gdp:.3%}, WACC-0.5%)",
            ),
            ValuationAssumption("Terminal Growth (Low)", round(tg_low, 4), "%", "Base − 0.5% (Low < Base < High)"),
            ValuationAssumption("Terminal Growth (High)", round(tg_high, 4), "%", "Base + 0.5% (not GDP-capped)"),
            ValuationAssumption("Cost of Equity (CAPM)", round(wacc_bd.cost_of_equity, 4), "%", wacc_bd.sources.get("ke", "")),
            ValuationAssumption(
                "Cost of Debt (after-tax)", round(wacc_bd.after_tax_cost_of_debt, 4), "%",
                wacc_bd.sources.get("kd (after-tax)", ""),
            ),
            ValuationAssumption("Effective Tax Rate", round(wacc_bd.effective_tax_rate, 4), "%", wacc_bd.sources.get("ETR", "")),
            ValuationAssumption(
                "Capital Structure",
                f"E={wacc_bd.weight_equity:.1%} / D={wacc_bd.weight_debt:.1%}",
                None,
                wacc_bd.sources.get("Weights", ""),
            ),
            ValuationAssumption("Risk-Free Rate", round(wacc_bd.risk_free_rate, 4), "%", wacc_bd.sources.get("Rf", "")),
            ValuationAssumption("Equity Risk Premium", round(wacc_bd.equity_risk_premium, 4), "%", wacc_bd.sources.get("ERP", "")),
            ValuationAssumption("Beta (winsorized)", round(wacc_bd.beta, 3), "x", wacc_bd.sources.get("β", "")),
            ValuationAssumption("Forecast Horizon", self.horizon, "years", "Default"),
        ]
        sanity_note = wacc_bd.sanity_message()
        if wacc_bd.sanity_status != "Within Range":
            notes_extra: List[str] = [sanity_note]
        else:
            notes_extra: List[str] = [sanity_note]

        from forecasts.nwc_utils import business_type_from_profile

        forecast_engine = ForecastEngine(
            horizon_years=self.horizon,
            business_type=business_type_from_profile(profile),
        )
        forecasts = forecast_engine.build_all(data).get(ScenarioType.BASE, [])
        if not forecasts:
            forecasts = forecast_engine._build_scenario(data, ScenarioType.BASE) or []

        if not forecasts:
            return ValuationResult(
                model_name=self.model_name,
                status=SolverStatus.INSUFFICIENT_DATA,
                notes=["Unable to build forecast projections"] + notes_extra,
                assumptions=assumptions,
                data_quality_score=data.quality.data_quality_score,
            )

        pv_explicit, tv, pv_tv, fcf_list, tv_pct = self._pv_calculations(forecasts, wacc, tg)

        # ---- Low/High Terminal Growth valuations for reference ----
        _ev_low = pv_explicit + self._pv_tv_only(forecasts, wacc, tg_low)[1]
        _pps_low = (_ev_low - data.market.net_debt_or_zero()) / (
            forecasts[-1].shares_outstanding or (data.ttm.shares_outstanding if data.ttm else 1) or 1
        )
        _ev_high = pv_explicit + self._pv_tv_only(forecasts, wacc, tg_high)[1]
        _pps_high = (_ev_high - data.market.net_debt_or_zero()) / (
            forecasts[-1].shares_outstanding or (data.ttm.shares_outstanding if data.ttm else 1) or 1
        )

        ev = pv_explicit + pv_tv
        net_debt = data.market.net_debt_or_zero()
        equity_val = ev - net_debt
        shares = forecasts[-1].shares_outstanding or (data.ttm.shares_outstanding if data.ttm else None)
        if shares is None or shares <= 0 or equity_val is None:
            return ValuationResult(
                model_name=self.model_name,
                status=SolverStatus.INFEASIBLE,
                notes=["Invalid equity value or shares"] + notes_extra,
                assumptions=assumptions,
                data_quality_score=data.quality.data_quality_score,
            )
        pps = equity_val / shares
        if wacc <= tg:
            status = SolverStatus.APPROXIMATE
            notes_extra.append(f"Warning: WACC ({wacc:.2%}) <= TerminalGrowth ({tg:.2%}); inflated TV")
        else:
            status = SolverStatus.SOLVED
        if tv_pct > 0.85:
            notes_extra.append(f"Very high terminal value weight: {tv_pct:.1%}")

        breakdown = {
            "pv_explicit": pv_explicit,
            "terminal_value": tv,
            "pv_terminal_value": pv_tv,
            "enterprise_value": ev,
            "net_debt": net_debt,
            "equity_value": equity_val,
            "shares_outstanding": shares,
            "value_per_share": pps,
            "wacc": wacc,
            "terminal_growth": tg,
            "terminal_growth_low": tg_low,
            "terminal_growth_high": tg_high,
            "value_per_share_low_g": _pps_low,
            "value_per_share_high_g": _pps_high,
            "tv_percent_of_ev": tv_pct,
            "forecast_fcf": fcf_list,
            "wacc_breakdown": wacc_bd,
            "tvg_range": tvg,
            "industry_range": (wacc_bd.industry_range_min, wacc_bd.industry_range_max, wacc_bd.industry_label),
            "sanity_status": wacc_bd.sanity_status,
        }

        return ValuationResult(
            model_name=self.model_name,
            status=status,
            value_per_share=pps,
            enterprise_value=ev,
            equity_value=equity_val,
            assumptions=assumptions,
            notes=notes_extra,
            breakdown=breakdown,
            data_quality_score=data.quality.data_quality_score,
        )

    def _pv_tv_only(self, forecasts: List[Any], wacc: float, tg: float) -> Tuple[float, float]:
        """Returns (terminal_value, pv_of_terminal_value) — helper for Low/High TVG."""
        last_fcf = None
        for fp in forecasts:
            fcf = fp.free_cash_flow or 0.0
            last_fcf = fcf
        if last_fcf is None or last_fcf <= 0:
            last_fcf = sum(abs(p.free_cash_flow or 0) for p in forecasts) / max(1, len(forecasts)) or 1.0
        n = len(forecasts)
        if wacc > tg:
            tv = (last_fcf * (1 + tg)) / (wacc - tg)
        else:
            tv = last_fcf * (1 + tg) / max(1e-4, (wacc - tg + 1e-3))
        pv_tv = tv / (1 + wacc) ** n
        return tv, pv_tv

    def _pv_calculations(
        self, forecasts: List[Any], wacc: float, tg: float
    ) -> Tuple[float, float, float, List[float], float]:
        pv_explicit = 0.0
        fcf_list: List[float] = []
        last_fcf = None
        for i, fp in enumerate(forecasts):
            t = i + 1
            fcf = fp.free_cash_flow or 0.0
            fcf_list.append(fcf)
            last_fcf = fcf
            pv_explicit += fcf / (1 + wacc) ** t

        if last_fcf is None or last_fcf <= 0:
            last_fcf = sum(abs(f) for f in fcf_list) / max(1, len(fcf_list))
            if last_fcf <= 0:
                last_fcf = 1.0

        n = len(forecasts)
        if wacc > tg:
            tv = (last_fcf * (1 + tg)) / (wacc - tg)
        else:
            tv = last_fcf * (1 + tg) / max(1e-4, (wacc - tg + 1e-3))
        pv_tv = tv / (1 + wacc) ** n
        total_ev = pv_explicit + pv_tv
        tv_pct = pv_tv / total_ev if total_ev > 0 else 0.0
        return pv_explicit, tv, pv_tv, fcf_list, tv_pct

    def _estimate_wacc(self, data: Any, profile: Any) -> float:
        """Legacy compatibility wrapper (used by reverse_dcf and other internal modules).

        Delegates to :class:`~valuation.wacc.WaccCalculator`; returns a single float WACC.
        """
        wb = self._wacc_calc.calculate(data, profile)
        return float(wb.wacc)


__all__ = ["DCFModel"]
