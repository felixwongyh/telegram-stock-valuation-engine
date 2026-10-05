"""
analysis/scenario.py - Bear/Base/Bull Scenario Analysis
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from config import (
    DEFAULT_DCF_CONFIG,
    DEFAULT_FORECAST_HORIZON_YEARS,
    DEFAULT_SCENARIO_CONFIG,
    ScenarioConfig,
    ScenarioType,
    get_logger,
)
from config import DCFConfig
from data.models import FinancialData
from forecasts.forecast import ForecastEngine
from models.dcf import DCFModel

log = get_logger("analysis.scenario")


@dataclass
class ScenarioValuation:
    scenario: str
    value_per_share: Optional[float]
    wacc: float
    terminal_growth: float
    notes: List[str] = field(default_factory=list)
    assumptions: Dict[str, Any] = field(default_factory=dict)


class ScenarioAnalyzer:
    """Runs DCF under Bear/Base/Bull scenarios."""

    def __init__(
        self,
        scenario_cfg: ScenarioConfig = DEFAULT_SCENARIO_CONFIG,
        dcf_cfg: DCFConfig = DEFAULT_DCF_CONFIG,
        horizon: int = DEFAULT_FORECAST_HORIZON_YEARS,
    ) -> None:
        self.sc = scenario_cfg
        self.dc = dcf_cfg
        self.horizon = horizon
        self.forecast = ForecastEngine(horizon_years=horizon, scenario_config=scenario_cfg)

    def run_all(self, data: FinancialData, profile: Any) -> Dict[str, ScenarioValuation]:
        results: Dict[str, ScenarioValuation] = {}
        for s in ScenarioType:
            results[s.value] = self._run_one(data, profile, s)
        return results

    def _run_one(self, data: FinancialData, profile: Any, st: ScenarioType) -> ScenarioValuation:
        if st == ScenarioType.BEAR:
            wacc_add = self.sc.bear_wacc_add
            tv_add = self.sc.bear_tv_add
        elif st == ScenarioType.BULL:
            wacc_add = self.sc.bull_wacc_add
            tv_add = self.sc.bull_tv_add
        else:
            wacc_add = 0.0
            tv_add = 0.0

        dcfg = DCFConfig(
            risk_free_rate=self.dc.risk_free_rate,
            equity_risk_premium=self.dc.equity_risk_premium,
            default_unlevered_beta=self.dc.default_unlevered_beta,
            default_terminal_growth=self.dc.default_terminal_growth + tv_add,
            min_wacc=self.dc.min_wacc,
            max_wacc=self.dc.max_wacc,
            max_terminal_growth=self.dc.max_terminal_growth,
            tax_rate=self.dc.tax_rate,
        )
        model = DCFModel(config=dcfg, forecast_horizon=self.horizon)
        forecasts = self.forecast.build_all(data).get(st, [])

        try:
            from config import ScenarioType as ST
            if st == ST.BASE:
                result = model.calculate(data, profile)
            else:
                from models.base import ValuationAssumption
                from config import SolverStatus
                wacc = model._estimate_wacc(data, profile) + wacc_add
                tg = dcfg.default_terminal_growth
                if not forecasts:
                    forecasts = self.forecast._build_scenario(data, st) or []
                if not forecasts:
                    return ScenarioValuation(
                        scenario=st.value,
                        value_per_share=None,
                        wacc=wacc,
                        terminal_growth=tg,
                        notes=["No forecast data available"],
                    )
                pv_explicit, tv, pv_tv, fcf_list, tv_pct = model._pv_calculations(forecasts, wacc, tg)
                ev = pv_explicit + pv_tv
                net_debt = data.market.net_debt_or_zero()
                eq = ev - net_debt
                shares = forecasts[-1].shares_outstanding or (data.ttm.shares_outstanding if data.ttm else None)
                if shares and shares > 0 and eq is not None:
                    pps = eq / shares
                    notes = []
                    if tv_pct > 0.85:
                        notes.append(f"TV weight {tv_pct:.1%}")
                    return ScenarioValuation(
                        scenario=st.value,
                        value_per_share=pps,
                        wacc=wacc,
                        terminal_growth=tg,
                        notes=notes,
                        assumptions={"tv_pct": tv_pct, "ev": ev, "equity": eq},
                    )
                return ScenarioValuation(
                    scenario=st.value, value_per_share=None, wacc=wacc, terminal_growth=tg,
                    notes=["Invalid shares or equity"],
                )
        except Exception as e:
            log.exception(f"Scenario {st.value} failed: {e}")
            return ScenarioValuation(
                scenario=st.value,
                value_per_share=None,
                wacc=self.dc.risk_free_rate,
                terminal_growth=self.dc.default_terminal_growth,
                notes=[f"Error: {e}"],
            )

        if result.is_success():
            return ScenarioValuation(
                scenario=st.value,
                value_per_share=result.value_per_share,
                wacc=result.breakdown.get("wacc", 0),
                terminal_growth=result.breakdown.get("terminal_growth", 0),
                notes=result.notes,
                assumptions={
                    "tv_pct": result.breakdown.get("tv_percent_of_ev"),
                    "ev": result.breakdown.get("enterprise_value"),
                },
            )
        return ScenarioValuation(
            scenario=st.value,
            value_per_share=None,
            wacc=self.dc.risk_free_rate,
            terminal_growth=self.dc.default_terminal_growth,
            notes=result.notes,
        )


__all__ = ["ScenarioAnalyzer", "ScenarioValuation"]
