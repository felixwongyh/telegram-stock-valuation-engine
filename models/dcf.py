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
    resolve_forecast_horizon,
)
from data.models import FinancialData
from forecasts.fcf_projection import gordon_terminal_value
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
        forecast_horizon: Optional[int] = None,
    ) -> None:
        super().__init__()
        self.cfg = config
        # ``horizon`` keeps a concrete value for backward compatibility, but the
        # authoritative window is resolved per business type in ``calculate``
        # (``resolve_forecast_horizon``). Pass an int here only to force an
        # explicit override.
        self._horizon_override = forecast_horizon
        self.horizon = (
            forecast_horizon if forecast_horizon is not None
            else DEFAULT_FORECAST_HORIZON_YEARS
        )
        self._wacc_calc = WaccCalculator(config=config)
        self._tvg_calc = TerminalGrowthCalculator(
            long_term_nominal_gdp=LONG_TERM_NOMINAL_GDP,
        )

    def _resolve_horizon(self, profile: Any) -> int:
        """Explicit override if provided, else per-business-type resolution."""
        if self._horizon_override is not None:
            return int(self._horizon_override)
        from forecasts.nwc_utils import business_type_from_profile

        return resolve_forecast_horizon(business_type_from_profile(profile))

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
                f"Long-run stable rate: min(norm={tvg.normalized_growth:.3%}, LT_GDP={tvg.long_term_nominal_gdp:.3%}, WACC-0.5%)",
            ),
            ValuationAssumption("Terminal Growth (Low)", round(tg_low, 4), "%", "Conservative scenario: Base − 0.5% (Low < Base < High)"),
            ValuationAssumption(
                "Terminal Growth (High)", round(tg_high, 4), "%",
                "Optimistic scenario: may exceed long-run GDP; only Gordon-capped at "
                "WACC−0.5%, NOT a long-run stable terminal growth rate"
                if tvg.high_exceeds_gdp else
                "Optimistic scenario: Base + 0.5% (within long-run GDP; Gordon-capped at WACC−0.5%)",
            ),
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
            ValuationAssumption("Forecast Horizon", self._resolve_horizon(profile), "years",
                                "Per-type (resolve_forecast_horizon)"
                                if self._horizon_override is None else "Explicit override"),
        ]
        sanity_note = wacc_bd.sanity_message()
        if wacc_bd.sanity_status != "Within Range":
            notes_extra: List[str] = [sanity_note]
        else:
            notes_extra: List[str] = [sanity_note]

        from forecasts.nwc_utils import business_type_from_profile

        # Resolve the projection window from the profile (never the shared
        # instance), so DCF / Reverse DCF / Scenario / Sensitivity / MC all use
        # one horizon per business type (Session #16).
        horizon = self._resolve_horizon(profile)
        forecast_engine = ForecastEngine(
            horizon_years=horizon,
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

        # A negative terminal-year FCF suppresses the terminal value (no sign
        # flip — see gordon_terminal_value). Surface it loudly instead of hiding
        # it behind a fabricated positive TV (Session #16).
        terminal_fcf_negative = bool(fcf_list) and fcf_list[-1] <= 0

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
        # Floor negative equity to 0 (insolvency / equity wipeout), consistent
        # with scenario analysis and sensitivity matrix. A negative per-share
        # value is not a price target — it signals that EV < net debt.
        pps_raw = pps
        if pps < 0:
            notes_extra.insert(0,
                f"⚠️ 股权价值归零（原始推算 ${pps:.2f} < 0）：EV 低于净债务，"
                "存在资不抵债 / 股权被清零风险"
            )
            pps = 0.0

        # ---- WACC-range valuation (Session #07) --------------------------
        # When the calculated WACC sits outside the industry sanity band, a single
        # point estimate hides how much of the conclusion is driven by that WACC.
        # Re-value at the industry band's edges so the report can show a range.
        ir_lo = wacc_bd.industry_range_min
        ir_hi = wacc_bd.industry_range_max
        _pps_wacc_lo = _pps_wacc_hi = None
        for _tag, _w in (("lo", ir_lo), ("hi", ir_hi)):
            try:
                if _w > tg and shares > 0:
                    _pe, _tv, _ptv, _f, _pct = self._pv_calculations(forecasts, _w, tg)
                    _v = (_pe + _ptv - net_debt) / shares
                    if _tag == "lo":
                        _pps_wacc_lo = _v
                    else:
                        _pps_wacc_hi = _v
            except Exception:
                pass

        if terminal_fcf_negative:
            status = SolverStatus.APPROXIMATE
            notes_extra.append(
                f"⚠️ 终期 FCF 为负（第 {len(fcf_list)} 年 ${fcf_list[-1]:,.0f}）：已抑制终值"
                "（不做符号翻转），估值 = 显式期现值下限；须明确转型（turnaround）假设才成立"
            )
        elif wacc <= tg:
            status = SolverStatus.APPROXIMATE
            notes_extra.append(f"Warning: WACC ({wacc:.2%}) <= TerminalGrowth ({tg:.2%}); inflated TV")
        else:
            status = SolverStatus.SOLVED
        if tv_pct > 1.5:
            # Terminal value swamps EV: the explicit-period PV of FCF is deeply
            # negative (pre-profit build-out), so the point value is essentially
            # the terminal assumption restated. It is NOT a fair-value estimate.
            notes_extra.append(
                f"⚠ DCF point value unreliable: terminal value = {tv_pct:.1%} of EV "
                f"(explicit-period FCF PV is negative) — value is dominated by the "
                f"terminal-growth assumption"
            )
        elif tv_pct > 0.85:
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
            "value_per_share_raw": pps_raw,
            "wacc": wacc,
            "terminal_growth": tg,
            "terminal_growth_low": tg_low,
            "terminal_growth_high": tg_high,
            "value_per_share_low_g": _pps_low,
            "value_per_share_high_g": _pps_high,
            "wacc_lo_industry": ir_lo,
            "wacc_hi_industry": ir_hi,
            "value_per_share_wacc_lo": _pps_wacc_lo,
            "value_per_share_wacc_hi": _pps_wacc_hi,
            "tv_percent_of_ev": tv_pct,
            "terminal_fcf_negative": terminal_fcf_negative,
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
        """Returns (terminal_value, pv_of_terminal_value) — helper for Low/High TVG.

        Routed through the single ``gordon_terminal_value`` helper so the Low/High
        TVG reference values obey the SAME negative-terminal-FCF suppression and
        WACC−g floor as the base case (no sign flip, no divergent floor).
        """
        last_fcf = None
        for fp in forecasts:
            last_fcf = fp.free_cash_flow or 0.0
        n = len(forecasts)
        tv_res = gordon_terminal_value(last_fcf, wacc, tg, n)
        return tv_res.terminal_value, tv_res.pv_terminal_value

    def _pv_calculations(
        self, forecasts: List[Any], wacc: float, tg: float
    ) -> Tuple[float, float, float, List[float], float]:
        pv_explicit = 0.0
        fcf_list: List[float] = []
        for i, fp in enumerate(forecasts):
            t = i + 1
            fcf = fp.free_cash_flow or 0.0
            fcf_list.append(fcf)
            pv_explicit += fcf / (1 + wacc) ** t

        # Single honest terminal value: a non-positive terminal-year FCF
        # suppresses the TV (no sign flip) instead of fabricating a positive one
        # (Session #16 — see forecasts.fcf_projection.gordon_terminal_value).
        n = len(forecasts)
        tv_res = gordon_terminal_value(fcf_list[-1] if fcf_list else None, wacc, tg, n)
        tv = tv_res.terminal_value
        pv_tv = tv_res.pv_terminal_value
        total_ev = pv_explicit + pv_tv
        tv_pct = pv_tv / total_ev if total_ev > 0 else 0.0
        return pv_explicit, tv, pv_tv, fcf_list, tv_pct

    def _estimate_wacc(self, data: Any, profile: Any) -> float:
        """Legacy compatibility wrapper (used by reverse_dcf and other internal modules).

        Delegates to :class:`~valuation.wacc.WaccCalculator`; returns a single float WACC.
        """
        wb = self._wacc_calc.calculate(data, profile)
        return float(wb.wacc)

    def _estimate_wacc_breakdown(self, data: Any, profile: Any):
        """Return the full :class:`WaccBreakdown` (WACC + resolved Rf + audit).

        Consumers that need a *single source of truth* for the risk-free rate the
        WACC was actually built from (e.g. the reverse-DCF implied-WACC floor)
        MUST read ``risk_free_rate`` here rather than re-resolving Rf — otherwise
        the implied constraint can silently diverge from the reported WACC
        (Session #33).
        """
        return self._wacc_calc.calculate(data, profile)


__all__ = ["DCFModel"]
