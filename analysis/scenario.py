"""
analysis/scenario.py - Bear/Base/Bull Scenario Analysis
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from config import (
    DEFAULT_DCF_CONFIG,
    DEFAULT_SCENARIO_CONFIG,
    ScenarioConfig,
    ScenarioType,
    get_logger,
    resolve_forecast_horizon,
)
from config import DCFConfig
from data.models import FinancialData
from forecasts.forecast import ForecastEngine
from forecasts.nwc_utils import business_type_from_profile
from models.dcf import DCFModel
from valuation.caliber import CaliberContract, DiscountCaliber, build_caliber_contract
from valuation.terminal_growth import TerminalGrowthCalculator

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
    """Runs DCF under Bear/Base/Bull scenarios.

    Financial institutions (banks / insurers) are the exception: DCF calibers
    (FCF, Net Debt, EV, WACC) are undefined for a borrowing business, so their
    Bear/Base/Bull band is produced by the *applicable* bank model (Bank RIM),
    varied along the cost of equity.
    """

    # Cost-of-equity scenario width for financials, expressed in β units. The
    # CAPM shift is applied on top of the unified β exit, then clamp-guarded to
    # the winsorised band [0.30, 2.50] used everywhere else.
    _FIN_BETA_STEP = 0.30
    # Operating-driver width for financials, expressed as a *relative* swing on
    # ROE (the aggregate outcome of net interest margin and credit costs). Bear
    # = ROE down, Bull = ROE up. ROE is the best operating proxy available from
    # the TTM data; a true NIM / provision split would need line-item data.
    _FIN_ROE_SHOCK = 0.20

    def __init__(
        self,
        scenario_cfg: ScenarioConfig = DEFAULT_SCENARIO_CONFIG,
        dcf_cfg: DCFConfig = DEFAULT_DCF_CONFIG,
        horizon: Optional[int] = None,
    ) -> None:
        self.sc = scenario_cfg
        self.dc = dcf_cfg
        # Horizon is resolved per call from the profile (Session #16) so scenario
        # values share the exact DCF / Reverse DCF window. Pass an int only to
        # force an explicit override.
        self._horizon_override = horizon
        self.scenario_cfg = scenario_cfg
        self.forecast: Optional[ForecastEngine] = None

    def _resolve_horizon(self, profile: Any) -> int:
        if self._horizon_override is not None:
            return int(self._horizon_override)
        return resolve_forecast_horizon(business_type_from_profile(profile))

    def _forecast_engine(self, profile: Any, horizon: int) -> ForecastEngine:
        return ForecastEngine(
            horizon_years=horizon,
            scenario_config=self.scenario_cfg,
            business_type=business_type_from_profile(profile),
        )

    def run_all(self, data: FinancialData, profile: Any) -> Dict[str, ScenarioValuation]:
        # The discount caliber is an ENGINE output (CaliberContract), not a
        # render-time guess. When the engine declares a cost-of-equity caliber
        # (banks / insurers) the DCF path is a forbidden caliber here.
        contract = build_caliber_contract(profile)
        if contract.discount is DiscountCaliber.COST_OF_EQUITY:
            return self._run_financial_scenarios(data, profile, contract)
        horizon = self._resolve_horizon(profile)
        self.forecast = self._forecast_engine(profile, horizon)
        results: Dict[str, ScenarioValuation] = {}
        for s in ScenarioType:
            results[s.value] = self._run_one(data, profile, s, horizon)
        return results

    def _run_financial_scenarios(
        self, data: FinancialData, profile: Any,
        contract: Optional[CaliberContract] = None,
    ) -> Dict[str, ScenarioValuation]:
        """Bear/Base/Bull for banks & insurers via the residual-income model.

        A DCF scenario for a bank is a forbidden caliber: the report itself
        flags "DCF unreliable for financial institutions", so presenting a
        WACC/terminal-growth band here would contradict both that note and the
        bank-model median (Recursion SOFI round2 fix).

        Scenarios vary *two* financial-specific drivers instead of reusing DCF:
          * discount side — cost of equity around the unified β exit, and
          * operating side — ROE (≈ net interest margin / credit cost), the
            residual-income model's profitability driver.
        This gives the band an operating dimension rather than pure rate
        sensitivity (Recursion SOFI round3 follow-up).
        """
        from models.bank import BankRIMModel
        from valuation.wacc import resolve_effective_beta

        contract = contract or build_caliber_contract(profile)
        discount_label = contract.discount.value
        base_beta = float(resolve_effective_beta(data).beta)
        model = BankRIMModel()

        # Probe the base case once to read the TTM-derived ROE the model uses.
        base_roe: Optional[float] = None
        try:
            probe = model.calculate(data, profile, beta=base_beta)
            if probe.is_success() and probe.breakdown:
                base_roe = probe.breakdown.get("roe")
        except Exception as e:  # pragma: no cover - defensive
            log.exception(f"Bank RIM base probe failed: {e}")

        plan = (
            (ScenarioType.BEAR, +self._FIN_BETA_STEP, -self._FIN_ROE_SHOCK),
            (ScenarioType.BASE, 0.0, 0.0),
            (ScenarioType.BULL, -self._FIN_BETA_STEP, +self._FIN_ROE_SHOCK),
        )
        out: Dict[str, ScenarioValuation] = {}
        for st, shift, roe_shock in plan:
            beta = min(2.50, max(0.30, base_beta + shift))
            roe_override = (
                float(base_roe) * (1.0 + roe_shock)
                if base_roe is not None and roe_shock else None
            )
            drivers: List[str] = []
            if shift:
                drivers.append(f"折现率 ke {'↑' if shift > 0 else '↓'}（β{shift:+.2f}）")
            if roe_override is not None:
                drivers.append(f"经营性 ROE {'↓' if roe_shock < 0 else '↑'}"
                               f"（{float(base_roe):.2%}→{roe_override:.2%}）")
            driver_txt = " + ".join(drivers) if drivers else "基准假设（未加驱动偏移）"

            try:
                r = model.calculate(data, profile, beta=beta, roe_override=roe_override)
            except Exception as e:  # pragma: no cover - defensive
                log.exception(f"Bank RIM scenario {st.value} failed: {e}")
                out[st.value] = ScenarioValuation(
                    scenario=st.value, value_per_share=None, wacc=0.0,
                    terminal_growth=0.0, notes=[f"Error: {e}"],
                    assumptions={
                        "model": "Bank RIM", "discount_label": discount_label,
                        "drivers": driver_txt,
                    },
                )
                continue
            bd = getattr(r, "breakdown", None) or {}
            ke = bd.get("cost_of_equity")
            roe_used = bd.get("roe")
            ok = r.is_success() and r.value_per_share is not None
            if ke is not None:
                roe_bit = (
                    f"；ROE（≈ 净息差/信用成本的综合体现，APPROXIMATE）={float(roe_used):.2%}"
                    if roe_used is not None else ""
                )
                notes = [
                    f"金融标的情景：以 Bank RIM（残差收益）计算，折现率 = 权益成本 "
                    f"ke={float(ke):.2%}（β={beta:.2f}）{roe_bit}；DCF（WACC/净债务/EV）对"
                    f"银行/保险不适用",
                    f"情景驱动：{driver_txt}",
                ]
            else:
                notes = ["金融标的情景：DCF 不适用，改用 Bank RIM 但成本法未解出"]
            if ok and r.notes:
                notes.append(r.notes[0])
            out[st.value] = ScenarioValuation(
                scenario=st.value,
                value_per_share=float(r.value_per_share) if ok else None,
                wacc=float(ke) if ke is not None else 0.0,
                terminal_growth=0.0,
                notes=notes,
                assumptions={
                    "model": "Bank RIM",
                    "beta": beta,
                    "discount_label": discount_label,
                    "cost_of_equity": ke,
                    "roe": roe_used,
                    "drivers": driver_txt,
                },
            )
        return out

    def _run_one(
        self, data: FinancialData, profile: Any, st: ScenarioType, horizon: int
    ) -> ScenarioValuation:
        if st == ScenarioType.BEAR:
            wacc_add = self.sc.bear_wacc_add
        elif st == ScenarioType.BULL:
            wacc_add = self.sc.bull_wacc_add
        else:
            wacc_add = 0.0

        dcfg = DCFConfig(
            risk_free_rate=self.dc.risk_free_rate,
            equity_risk_premium=self.dc.equity_risk_premium,
            default_unlevered_beta=self.dc.default_unlevered_beta,
            default_terminal_growth=self.dc.default_terminal_growth,
            min_wacc=self.dc.min_wacc,
            max_wacc=self.dc.max_wacc,
            max_terminal_growth=self.dc.max_terminal_growth,
            tax_rate=self.dc.tax_rate,
        )
        model = DCFModel(config=dcfg, forecast_horizon=horizon)

        try:
            from config import ScenarioType as ST
            if st == ST.BASE:
                result = model.calculate(data, profile)
            else:
                wacc = model._estimate_wacc(data, profile) + wacc_add
                tvg = TerminalGrowthCalculator().calculate(data, wacc=wacc)
                if st == ST.BEAR:
                    tg = tvg.low
                elif st == ST.BULL:
                    tg = tvg.high
                else:
                    tg = tvg.base
                tg = min(max(0.0, tg), wacc - 0.001)

                # ---- Use BASE forecasts for all scenarios (consistent with
                # sensitivity matrix). Previously, bear/bull used scenario-
                # adjusted forecasts (revenue×0.7, margin×0.7, etc.), which
                # caused the scenario values to diverge from the sensitivity
                # matrix at the same (WACC, TG) pair.
                # This is the fix for P0-1: scenario values must be reproducible
                # in the sensitivity matrix.
                forecasts = self.forecast.build_all(data).get(ST.BASE, [])
                if not forecasts:
                    forecasts = self.forecast._build_scenario(data, ST.BASE) or []

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
                    if pps < 0:
                        # Negative per-share equity is not a price target — floor to 0
                        # and flag equity-wipeout / insolvency risk instead.
                        notes.append(
                            f"⚠️ 股权价值归零（原始推算 ${pps:.2f} < 0）：该情景下 EV 低于净债务，"
                            "存在资不抵债 / 股权被清零风险"
                        )
                        pps = 0.0
                    if tv_pct > 0.85:
                        notes.append(f"TV weight {tv_pct:.1%}")
                    notes.append(
                        f"Scenario uses base forecasts with WACC={wacc:.4f}, g={tg:.4f} "
                        f"(consistent with sensitivity matrix)"
                    )
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
            pps = result.value_per_share
            notes = list(result.notes) if result.notes else []
            tv_pct = result.breakdown.get("tv_percent_of_ev") if result.breakdown else None
            # Apply the same negative-equity floor as Bear/Bull scenarios
            # (a negative per-share value is not a price target — it signals
            # equity-wipeout / insolvency risk).
            if pps is not None and pps < 0:
                notes.insert(0,
                    f"⚠️ 股权价值归零（原始推算 ${pps:.2f} < 0）：该情景下 EV 低于净债务，"
                    "存在资不抵债 / 股权被清零风险"
                )
                pps = 0.0
            return ScenarioValuation(
                scenario=st.value,
                value_per_share=pps,
                wacc=result.breakdown.get("wacc", 0) if result.breakdown else 0,
                terminal_growth=result.breakdown.get("terminal_growth", 0) if result.breakdown else 0,
                notes=notes,
                assumptions={
                    "tv_pct": tv_pct,
                    "ev": result.breakdown.get("enterprise_value") if result.breakdown else None,
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
